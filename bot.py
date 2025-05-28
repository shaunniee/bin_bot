import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
import ta

# === Load environment variables ===
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise Exception("Please set MONGO_URI in your .env file")
client = MongoClient(MONGO_URI)
db = client["tradingbot"]
backtest_collection = db["backtest_trades"]

# === Binance Testnet fetch function for 5m interval ===
def fetch_binance_testnet_klines_full(symbol="BTCUSDT", interval="5m", limit=1000):
    url = "https://testnet.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df[["timestamp", "open", "high", "low", "close", "volume"]]

# === Add indicators ===
def apply_indicators(df):
    df["EMA9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["EMA21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["RSI"] = ta.momentum.rsi(df["close"], window=14)
    df["ATR"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
    # VWAP calculation: using rolling weighted average price over volume
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["VWAP"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    macd = ta.trend.MACD(df["close"])
    df["MACD_diff"] = macd.macd_diff()
    adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["ADX"] = adx.adx()
    return df.dropna()

# === Market regime detection ===
def detect_market_regime(df):
    return "trending" if df["ADX"].iloc[-1] > 25 else "ranging"

# === Adaptive RSI bounds ===
def get_adaptive_rsi_bounds(df):
    atr = df["ATR"].iloc[-1]
    atr_mean = df["ATR"].rolling(window=20).mean().iloc[-1]
    return (45, 65) if atr > atr_mean else (40, 70)

# === Multiple buy signals definitions ===
def buy_signal_ema_rsi_vwap(df):
    latest = df.iloc[-1]
    regime = detect_market_regime(df)
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df)
    return (
        regime == "trending" and
        latest["EMA9"] > latest["EMA21"] and
        rsi_lower < latest["RSI"] < rsi_upper and
        latest["close"] > latest["VWAP"] and
        latest["ADX"] > 20
    )

def buy_signal_rsi_only(df):
    latest = df.iloc[-1]
    rsi_lower, rsi_upper = get_adaptive_rsi_bounds(df)
    return rsi_lower < latest["RSI"] < rsi_upper

def buy_signal_macd_adx(df):
    latest = df.iloc[-1]
    return latest["MACD_diff"] > 0 and latest["ADX"] > 25

# === Weighted buy decision combining signals ===
def should_buy(df, weights=[0.5, 0.3, 0.2], threshold=0.6):
    signals = [
        buy_signal_ema_rsi_vwap(df),
        buy_signal_rsi_only(df),
        buy_signal_macd_adx(df),
    ]
    score = sum(w for s, w in zip(signals, weights) if s)
    return score >= threshold, score

# === Sell signal ===
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

# === Backtest with parameter sweep ===
def backtest_with_sweep(df, symbol, 
                       tp_multipliers=[2.0, 2.5, 3.0], 
                       sl_multipliers=[1.0, 1.5, 2.0], 
                       max_holds=[30, 40, 50],
                       buy_weights=[ [0.5, 0.3, 0.2], [0.7, 0.2, 0.1] ],
                       buy_thresholds=[0.5, 0.6, 0.7]):
    all_trades = []
    total_combinations = len(tp_multipliers) * len(sl_multipliers) * len(max_holds) * len(buy_weights) * len(buy_thresholds)
    combo_counter = 0

    for tp_mult in tp_multipliers:
        for sl_mult in sl_multipliers:
            for max_hold in max_holds:
                for weights in buy_weights:
                    for threshold in buy_thresholds:
                        combo_counter += 1
                        trades = []
                        print(f"Running combo {combo_counter}/{total_combinations} - TP: {tp_mult}, SL: {sl_mult}, MaxHold: {max_hold}, Weights: {weights}, Threshold: {threshold}")

                        i = 0
                        while i < len(df) - max_hold:
                            window = df.iloc[:i+1]
                            buy_decision, score = should_buy(window, weights, threshold)
                            if buy_decision:
                                buy_price = df.iloc[i]["close"]
                                buy_time = df.iloc[i]["timestamp"]
                                atr = df.iloc[i]["ATR"]
                                tp = buy_price + tp_mult * atr
                                sl = buy_price - sl_mult * atr

                                exit_reason = None
                                exit_price = None
                                exit_time = None
                                duration = None
                                pnl = None

                                for j in range(i+1, i+max_hold):
                                    price = df.iloc[j]["close"]
                                    sub_window = df.iloc[:j+1]

                                    if price >= tp:
                                        exit_reason = "TP"
                                    elif price <= sl:
                                        exit_reason = "SL"
                                    elif should_sell(sub_window, buy_price):
                                        exit_reason = "Signal"
                                    elif j == i + max_hold - 1:
                                        exit_reason = "Timeout"
                                    else:
                                        continue

                                    exit_price = price
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
                                        "reason": exit_reason,
                                        "duration_min": duration,
                                        "tp_mult": tp_mult,
                                        "sl_mult": sl_mult,
                                        "max_hold": max_hold,
                                        "buy_weights": weights,
                                        "buy_threshold": threshold,
                                        "buy_signal_score": round(score, 2)
                                    }
                                    trades.append(trade)
                                    i = j  # jump forward after trade exit
                                    break
                            i += 1

                        print(f"Trades executed: {len(trades)}")
                        if trades:
                            backtest_collection.insert_many(trades)
                            print(f"Saved trades for combo {combo_counter} to MongoDB")
                        all_trades.extend(trades)
    return all_trades

# === Main execution ===
def main():
    symbol = "BTCUSDT"
    print("Fetching data from Binance Testnet...")
    df = fetch_binance_testnet_klines_full(symbol=symbol, interval="5m", limit=1000)
    df = apply_indicators(df)
    print(f"Data fetched and indicators applied. Total rows: {len(df)}")

    print("Starting backtest with parameter sweep...")
    trades = backtest_with_sweep(df, symbol)

    # Summary stats
    if trades:
        wins = sum(1 for t in trades if t["pnl"] > 0)
        avg_pnl = sum(t["pnl"] for t in trades) / len(trades)
        print(f"Total trades: {len(trades)}")
        print(f"Win rate: {wins}/{len(trades)} ({wins / len(trades) * 100:.2f}%)")
        print(f"Average PnL: {avg_pnl:.2f}")
    else:
        print("No trades executed.")

if __name__ == "__main__":
    main()
