import os
import ccxt
import pandas as pd
import time
from datetime import datetime, timezone
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
backtest_collection = db["backtest_trades"]

# === Set up exchange (for historical data only) ===
exchange = ccxt.binance()
symbol = "XRP/USDT"
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

# === Signal logic ===
def detect_market_regime(df):
    return "trending" if df["ADX"].iloc[-1] > 25 else "ranging"

def get_adaptive_rsi_bounds(df):
    atr = df["ATR"].iloc[-1]
    atr_mean = df["ATR"].rolling(window=20).mean().iloc[-1]
    return (45, 65) if atr > atr_mean else (40, 70)

def should_buy(df):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df)
    if (
        regime == "trending" and
        latest["EMA9"] > latest["EMA21"] and
        rsi_lower < latest["RSI"] < rsi_upper and
        latest["close"] > latest["VWAP"] and
        latest["ADX"] > 20
    ):
        return True
    return False

def should_sell(df, entry_price):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    atr = latest["ATR"]
    rsi = latest["RSI"]
    price = latest["close"]
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df)
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

# === Fetch & prepare data ===
def fetch_data(symbol, timeframe="5m", limit=1000):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return apply_indicators(df)

# === Backtest loop ===
def backtest(df, symbol):
    trades = []
    max_hold = 40  # max 40 candles = 200 mins on 5m chart

    for i in range(len(df) - max_hold):
        window = df.iloc[:i+1]
        if should_buy(window):
            buy_price = df.iloc[i]["close"]
            buy_time = df.iloc[i]["timestamp"]
            atr = df.iloc[i]["ATR"]
            tp = buy_price + 2.5 * atr
            sl = buy_price - 1.5 * atr

            for j in range(i+1, i+max_hold):
                price = df.iloc[j]["close"]
                sub_window = df.iloc[:j+1]

                if price >= tp:
                    reason = "TP"
                elif price <= sl:
                    reason = "SL"
                elif should_sell(sub_window, buy_price):
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
                    "duration_min": duration
                }
                trades.append(trade)
                break

    print(f"Completed {len(trades)} trades.")
    backtest_collection.insert_many(trades)
    return trades

# === Run ===
def main():
    df = fetch_data(symbol)
    results = backtest(df, symbol)
    # Summary
    wins = sum(1 for t in results if t["pnl"] > 0)
    avg_pnl = sum(t["pnl"] for t in results) / len(results)
    print(f"Win Rate: {wins}/{len(results)} ({wins/len(results)*100:.2f}%)")
    print(f"Avg PnL: {avg_pnl:.2f} USDT")

if __name__ == "__main__":
    main()
