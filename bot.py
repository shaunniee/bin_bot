import os
import ccxt
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from itertools import product

# === Load environment ===
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["tradingbot"]
backtest_collection = db["backtest_trades"]

exchange = ccxt.binance()
symbol = "BTC/USDT"
timeframe = "5m"

def apply_indicators(df):
    df["EMA9"] = EMAIndicator(close=df["close"], window=9).ema_indicator()
    df["EMA21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
    df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
    df["VWAP"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum() / df["volume"].cumsum()
    macd = MACD(close=df["close"])
    df["MACD_diff"] = macd.macd_diff()
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
    df["ADX"] = adx.adx()
    return df.dropna()

def detect_market_regime(df):
    return "trending" if df["ADX"].iloc[-1] > 25 else "ranging"

# Modified RSI bounds function to take parameters
def get_adaptive_rsi_bounds(df, rsi_lower_param, rsi_upper_param):
    # We use fixed params instead of adaptive for sweeper simplicity
    return (rsi_lower_param, rsi_upper_param)

def should_buy(df, rsi_lower_param, rsi_upper_param):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df, rsi_lower_param, rsi_upper_param)
    if (
        regime == "trending" and
        latest["EMA9"] > latest["EMA21"] and
        rsi_lower < latest["RSI"] < rsi_upper and
        latest["close"] > latest["VWAP"] and
        latest["ADX"] > 20
    ):
        return True
    return False

def should_sell(df, entry_price, rsi_lower_param, rsi_upper_param):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    atr = latest["ATR"]
    rsi = latest["RSI"]
    price = latest["close"]
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df, rsi_lower_param, rsi_upper_param)
    if regime == "trending":
        return (
            latest["EMA9"] < latest["EMA21"]
            or rsi > rsi_upper
            or price < entry_price - 1.5 * atr
            or latest["MACD_diff"] < 0
            or latest["ADX"] < 20
        )
    else:
        return rsi > rsi_upper or price < entry_price - 1.0 * atr or price < latest["VWAP"]

def fetch_data(symbol, timeframe="5m", limit=1000):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return apply_indicators(df)

def backtest(df, symbol, tp_mult, sl_mult, rsi_lower_param, rsi_upper_param, max_hold):
    trades = []
    for i in range(len(df) - max_hold):
        window = df.iloc[:i+1]
        if should_buy(window, rsi_lower_param, rsi_upper_param):
            buy_price = df.iloc[i]["close"]
            buy_time = df.iloc[i]["timestamp"]
            atr = df.iloc[i]["ATR"]
            tp = buy_price + tp_mult * atr
            sl = buy_price - sl_mult * atr

            for j in range(i+1, i+max_hold):
                price = df.iloc[j]["close"]
                sub_window = df.iloc[:j+1]

                if price >= tp:
                    reason = "TP"
                elif price <= sl:
                    reason = "SL"
                elif should_sell(sub_window, buy_price, rsi_lower_param, rsi_upper_param):
                    reason = "Signal"
                elif j == i + max_hold - 1:
                    reason = "Timeout"
                else:
                    continue

                exit_price = df.iloc[j]["close"]
                exit_time = df.iloc[j]["timestamp"]
                pnl = exit_price - buy_price
                duration = (exit_time - buy_time).total_seconds() / 60

                trade = {
                    "symbol": symbol,
                    "entry_time": buy_time.isoformat(),
                    "entry_price": round(buy_price, 2),
                    "exit_time": exit_time.isoformat(),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "duration_min": duration,
                    "tp_mult": tp_mult,
                    "sl_mult": sl_mult,
                    "rsi_lower": rsi_lower_param,
                    "rsi_upper": rsi_upper_param,
                    "max_hold": max_hold
                }
                trades.append(trade)
                break
    if trades:
        backtest_collection.insert_many(trades)
    return trades

def run_parameter_sweep():
    df = fetch_data(symbol)
    tp_multipliers = [2.0, 2.5, 3.0]
    sl_multipliers = [1.0, 1.5, 2.0]
    rsi_lowers = [40, 45, 50]
    rsi_uppers = [60, 65, 70]
    max_holds = [30, 40, 50]

    results = []

    combos = list(product(tp_multipliers, sl_multipliers, rsi_lowers, rsi_uppers, max_holds))
    print(f"Running {len(combos)} parameter combinations...")

    for tp_mult, sl_mult, rsi_low, rsi_high, max_hold in combos:
        trades = backtest(df, symbol, tp_mult, sl_mult, rsi_low, rsi_high, max_hold)
        if trades:
            wins = sum(1 for t in trades if t["pnl"] > 0)
            total = len(trades)
            avg_pnl = sum(t["pnl"] for t in trades) / total
            results.append({
                "tp_mult": tp_mult,
                "sl_mult": sl_mult,
                "rsi_lower": rsi_low,
                "rsi_upper": rsi_high,
                "max_hold": max_hold,
                "win_rate": wins / total,
                "avg_pnl": avg_pnl,
                "trades": total
            })
        else:
            results.append({
                "tp_mult": tp_mult,
                "sl_mult": sl_mult,
                "rsi_lower": rsi_low,
                "rsi_upper": rsi_high,
                "max_hold": max_hold,
                "win_rate": None,
                "avg_pnl": None,
                "trades": 0
            })

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by="avg_pnl", ascending=False)
    print(results_df.head(10))
    results_df.to_csv("parameter_sweep_results.csv", index=False)
    print("Parameter sweep completed and results saved to parameter_sweep_results.csv")

if __name__ == "__main__":
    run_parameter_sweep()
