import os
from binance.client import Client
import pandas as pd
import ta
import numpy as np
from itertools import product


# Load API keys from env
API_KEY = os.getenv('BINANCE_API_KEY', '')
API_SECRET = os.getenv('BINANCE_API_SECRET', '')
client = Client(API_KEY, API_SECRET, testnet=True)

def get_klines(symbol='BTCUSDT', interval='15m', limit=1000):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    return df[['open_time', 'open', 'high', 'low', 'close', 'volume']]

df = get_klines()

# Indicators
df['SMA_10'] = df['close'].rolling(10).mean()
df['SMA_30'] = df['close'].rolling(30).mean()
df['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
macd = ta.trend.MACD(df['close'])
df['MACD'] = macd.macd()
df['MACD_signal'] = macd.macd_signal()
df['BB_upper'] = ta.volatility.BollingerBands(df['close']).bollinger_hband()
df['BB_lower'] = ta.volatility.BollingerBands(df['close']).bollinger_lband()
df['ADX'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()

# Buy signals: return 1 if signal is triggered else 0
def buy_sma_cross(i):  # SMA10 crosses above SMA30
    return int(df['SMA_10'].iloc[i] > df['SMA_30'].iloc[i] and df['SMA_10'].iloc[i-1] <= df['SMA_30'].iloc[i-1])

def buy_rsi_oversold(i):
    return int(df['RSI'].iloc[i] < 30)

def buy_macd_cross(i):
    return int(df['MACD'].iloc[i] > df['MACD_signal'].iloc[i] and df['MACD'].iloc[i-1] <= df['MACD_signal'].iloc[i-1])

def buy_bb_lower_band(i):
    return int(df['close'].iloc[i] < df['BB_lower'].iloc[i])

def buy_adx_strong_trend(i):
    return int(df['ADX'].iloc[i] > 25)

buy_funcs = [buy_sma_cross, buy_rsi_oversold, buy_macd_cross, buy_bb_lower_band, buy_adx_strong_trend]

# Sell signals
def sell_profit_target(i, entry_price, target=0.02):
    return (df['close'].iloc[i] - entry_price) / entry_price >= target

def sell_rsi_overbought(i, entry_price=None):
    return int(df['RSI'].iloc[i] > 70)

def sell_macd_cross_down(i, entry_price=None):
    return int(df['MACD'].iloc[i] < df['MACD_signal'].iloc[i] and df['MACD'].iloc[i-1] >= df['MACD_signal'].iloc[i-1])

def sell_bb_upper_band(i, entry_price=None):
    return int(df['close'].iloc[i] > df['BB_upper'].iloc[i])

def sell_adx_weakening_trend(i, entry_price=None):
    return int(df['ADX'].iloc[i] < 20)

sell_funcs = [sell_profit_target, sell_rsi_overbought, sell_macd_cross_down, sell_bb_upper_band, sell_adx_weakening_trend]

# Combine buy signals weighted sum
def combined_buy_signal(i, weights):
    score = 0
    for w, f in zip(weights, buy_funcs):
        score += w * f(i)
    return score

# Combine sell signals weighted sum
def combined_sell_signal(i, weights, entry_price):
    score = 0
    for w, f in zip(weights, sell_funcs):
        # profit_target needs entry_price param, others ignore it safely
        if f == sell_profit_target:
            score += w * f(i, entry_price)
        else:
            score += w * f(i)
    return score

# Backtest weighted strategy for given weights
def backtest_strategy(buy_weights, sell_weights, buy_threshold=0.5, sell_threshold=0.5):
    position = False
    entry_price = 0
    profits = []
    trades = 0
    for i in range(1, len(df)):
        if not position:
            if combined_buy_signal(i, buy_weights) >= buy_threshold:
                position = True
                entry_price = df['close'].iloc[i]
        else:
            if combined_sell_signal(i, sell_weights, entry_price) >= sell_threshold:
                profit = (df['close'].iloc[i] - entry_price) / entry_price
                profits.append(profit)
                trades += 1
                position = False
    total_profit = sum(profits)
    avg_profit = total_profit / trades if trades > 0 else 0
    return total_profit, trades, avg_profit

# --- Grid search to find best weights ---
import itertools

# Weight candidates: try 0, 0.25, 0.5, 0.75, 1 for each indicator
weight_options = [0, 0.25, 0.5, 0.75, 1]

best_profit = -np.inf
best_buy_w = None
best_sell_w = None

# For brevity, limit grid search size by sampling combinations
# Full brute-force would be huge: 5^5 for buy * 5^5 for sell = 9,765,625 combos
# Let's try random samples instead for demonstration

np.random.seed(42)
samples = 1000

for _ in range(samples):
    buy_weights = np.random.choice(weight_options, size=len(buy_funcs))
    sell_weights = np.random.choice(weight_options, size=len(sell_funcs))
    profit, trades, avg = backtest_strategy(buy_weights, sell_weights)
    if profit > best_profit and trades > 5:  # Require minimum trades
        best_profit = profit
        best_buy_w = buy_weights
        best_sell_w = sell_weights

print("Best profit:", best_profit)
print("Best buy weights:", best_buy_w)
print("Best sell weights:", best_sell_w)

# Backtest again using best weights with thresholds at 0.5
total_profit, trades, avg_profit = backtest_strategy(best_buy_w, best_sell_w)

print(f"\nBacktest with best weights:")
print(f"Total Profit: {total_profit*100:.2f}% over {trades} trades, Avg Profit per trade: {avg_profit*100:.2f}%")
