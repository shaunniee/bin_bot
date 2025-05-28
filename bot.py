import os
import ccxt
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# === Load environment ===
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["tradingbot"]
backtest_collection = db["sweep_results"]

# === Set up exchange ===
exchange = ccxt.binance()
symbol = "BTC/USDT"
timeframe = "5m"

# === Indicators ===
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

# === Regime Detection ===
def detect_market_regime(df):
    return "trending" if df["ADX"].iloc[-1] > 25 else "ranging"

# === Buy Strategies ===
def basic_buy(df, rsi_bounds):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    rsi_lower, rsi_upper = rsi_bounds
    return (
        regime == "trending" and
        latest["EMA9"] > latest["EMA21"] and
        rsi_lower < latest["RSI"] < rsi_upper and
        latest["close"] > latest["VWAP"] and
        latest["ADX"] > 20
    )

# === Sell Strategy ===
def should_sell(df, entry_price, sl, rsi_bounds):
    latest = df.iloc[-1]
    price = latest["close"]
    atr = latest["ATR"]
    regime = detect_market_regime(df)
    rsi = latest["RSI"]
    rsi_lower, rsi_upper = rsi_bounds

    if regime == "trending":
        return (
            latest["EMA9"] < latest["EMA21"] or
            rsi > rsi_upper or
            price < entry_price - sl * atr or
            latest["MACD_diff"] < 0 or
            latest["ADX"] < 20
        )
    else:
        return (
            rsi > rsi_upper or
            price < entry_price - sl * atr or
            price < latest["VWAP"]
        )

# === Fetch historical data ===
def fetch_data(symbol, timeframe="5m", limit=1000):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return apply_indicators(df)

# === Backtest logic ===
def backtest(df, tp, sl, rsi_bounds, max_hold, buy_fn, buy_combo_name):
    trades = []
    for i in range(len(df) - max_hold):
        window = df.iloc[:i+1]
        if buy_fn(window, rsi_bounds):
            buy_price = df.iloc[i]["close"]
            buy_time = df.iloc[i]["timestamp"]
            atr = df.iloc[i]["ATR"]
            tp_price = buy_price + tp * atr
            sl_price = buy_price - sl * atr

            for j in range(i+1, i+max_hold):
                price = df.iloc[j]["close"]
                sub_window = df.iloc[:j+1]

                if price >= tp_price:
                    reason = "TP"
                elif price <= sl_price:
                    reason = "SL"
                elif should_sell(sub_window, buy_price, sl, rsi_bounds):
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
                    "entry_time": buy_time.isoformat(),
                    "entry_price": round(buy_price, 2),
                    "exit_time": exit_time.isoformat(),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "duration_min": duration,
                    "tp": tp,
                    "sl": sl,
                    "rsi_bounds": rsi_bounds,
                    "max_hold": max_hold,
                    "buy_combo": buy_combo_name
                }
                trades.append(trade)
                break

    wins = sum(1 for t in trades if t["pnl"] > 0)
    avg_pnl = sum(t["pnl"] for t in trades) / len(trades) if trades else 0
    win_rate = wins / len(trades) if trades else 0

    return trades, win_rate, avg_pnl

# === Sweep parameters ===
def sweep():
    df = fetch_data(symbol)
    results = []
    param_combos = [
        (tp, sl, rsi_bounds, max_hold)
        for tp in [2.0, 2.5, 3.0]
        for sl in [1.0, 1.5, 2.0]
        for rsi_bounds in [(40, 70), (45, 65)]
        for max_hold in [30, 40]
    ]

    for tp, sl, rsi_bounds, max_hold in param_combos:
        trades, win_rate, avg_pnl = backtest(df, tp, sl, rsi_bounds, max_hold, basic_buy, "basic_buy")
        results.append({
            "tp": tp,
            "sl": sl,
            "rsi_bounds": rsi_bounds,
            "max_hold": max_hold,
            "buy_combo": "basic_buy",
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "num_trades": len(trades)
        })

    df_results = pd.DataFrame(results)
    df_results["score"] = df_results["avg_pnl"] * 0.7 + df_results["win_rate"] * 100 * 0.3
    top10 = df_results.sort_values(by="score", ascending=False).head(10)
    print("\nTop 10 Best Strategies:\n")
    print(top10.to_string(index=False))

    # Optional: Save to MongoDB
    backtest_collection.insert_many(top10.to_dict("records"))

if __name__ == "__main__":
    sweep()
