import os
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Initialize Binance testnet
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})
exchange.set_sandbox_mode(True)

# Fetch historical OHLCV data
def fetch_ohlcv(symbol='BTC/USDT', timeframe='5m', limit=1000):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

# Apply indicators
def apply_indicators(df):
    df['EMA9'] = EMAIndicator(df['close'], window=9).ema_indicator()
    df['EMA21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['RSI'] = RSIIndicator(df['close'], window=14).rsi()
    df['ATR'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    df['VWAP'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    df['MACD'] = MACD(df['close']).macd_diff()
    df['ADX'] = ADXIndicator(df['high'], df['low'], df['close'], window=14).adx()
    return df
# Backtest logic
def backtest(df, initial_balance=10000):
    balance = initial_balance
    position = 0
    entry_price = 0
    equity_curve = []
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]

        # Buy condition
        if position == 0 and row['EMA9'] > row['EMA21'] and 40 < row['RSI'] < 70 and row['close'] > row['VWAP'] and row['ADX'] > 20:
            position = balance / row['close']
            entry_price = row['close']
            balance = 0
            trades.append((row.name, 'BUY', entry_price))

        # Sell condition
        elif position > 0 and (row['EMA9'] < row['EMA21'] or row['RSI'] > 70 or row['MACD'] < 0 or row['ADX'] < 20):
            balance = position * row['close']
            pnl = (row['close'] - entry_price) * position
            trades.append((row.name, 'SELL', row['close'], pnl))
            position = 0
            entry_price = 0

        equity = balance + position * row['close']
        equity_curve.append(equity)

    return equity_curve, trades

# Run backtest
df = fetch_ohlcv()
df = apply_indicators(df)
equity_curve, trades = backtest(df)

# Plot results
plt.figure(figsize=(12, 6))
plt.plot(df.index[-len(equity_curve):], equity_curve, label='Equity Curve')
plt.title('Backtest Equity Curve (5m)')
plt.xlabel('Date')
plt.ylabel('Equity')
plt.legend()
plt.grid(True)
plt.show()

# Print trades
for trade in trades:
    print(trade)
