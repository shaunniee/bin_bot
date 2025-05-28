import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
import ccxt
import pymongo
import os
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# --- Setup MongoDB ---
client = pymongo.MongoClient(MONGO_URI)
db = client["tradingbot"]
weights_collection = db["signal_weights"]

# --- 1. Load historical OHLCV data ---
exchange = ccxt.binance()
data = exchange.fetch_ohlcv('BTC/USDT', timeframe='5m', limit=1000)
df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

# --- 2. Apply indicators ---
df["EMA9"] = EMAIndicator(close=df["close"], window=9).ema_indicator()
df["EMA21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()
df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
df["VWAP"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum() / df["volume"].cumsum()
macd = MACD(close=df["close"])
df["MACD"] = macd.macd()
df["MACD_signal"] = macd.macd_signal()
df["MACD_diff"] = macd.macd_diff()
df["ADX"] = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14).adx()

# --- 3. Generate signal features ---
df["ema_cross"] = (df["EMA9"] > df["EMA21"]).astype(int)
df["rsi_in_bounds"] = df["RSI"].between(40, 70).astype(int)
df["above_vwap"] = (df["close"] > df["VWAP"]).astype(int)
df["adx_trending"] = (df["ADX"] > 25).astype(int)
df["macd_positive"] = (df["MACD_diff"] > 0).astype(int)

# --- 4. Define target label (profitability) ---
df["target_profit"] = df["close"].shift(-20) >= df["close"] + 2.5 * df["ATR"]
df.dropna(inplace=True)

# --- 5. Build feature matrix and target vector ---
X = df[["ema_cross", "rsi_in_bounds", "above_vwap", "adx_trending", "macd_positive"]]
y = df["target_profit"].astype(int)

# --- 6. Train logistic regression ---
model = LogisticRegression()
model.fit(X, y)

# --- 7. Show feature importance (weights) ---
weights = model.coef_[0]
features = X.columns
print("\nLearned Signal Weights:")

weights_dict = {"feature_weights": {}, "timestamp": pd.Timestamp.now().isoformat()}
for feat, w in zip(features, weights):
    print(f"{feat}: weight = {w:.2f}")
    weights_dict["feature_weights"][feat] = round(w, 4)

# --- 8. Store weights to MongoDB ---
weights_collection.insert_one(weights_dict)

# --- 9. Evaluate model ---
y_pred = model.predict(X)
print("\nModel Evaluation:")
print(classification_report(y, y_pred))
