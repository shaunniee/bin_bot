import os
from binance.client import Client
import pandas as pd
import ta

# --- Load API keys from environment variables ---
API_KEY = os.getenv('BINANCE_API_KEY', '')
API_SECRET = os.getenv('BINANCE_API_SECRET', '')

client = Client(API_KEY, API_SECRET, testnet=True)  # Use testnet

# --- Fetch historical klines from Binance ---
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

df = get_klines('BTCUSDT', '15m', 1000)

# --- Calculate indicators ---
df['SMA_10'] = df['close'].rolling(window=10).mean()
df['SMA_30'] = df['close'].rolling(window=30).mean()
df['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
macd = ta.trend.MACD(df['close'])
df['MACD'] = macd.macd()
df['MACD_signal'] = macd.macd_signal()

# --- Buy signals ---
def buy_sma_cross(df, i):
    return df['SMA_10'].iloc[i] > df['SMA_30'].iloc[i] and df['SMA_10'].iloc[i-1] <= df['SMA_30'].iloc[i-1]

def buy_rsi_oversold(df, i):
    return df['RSI'].iloc[i] < 30

def buy_macd_cross(df, i):
    return df['MACD'].iloc[i] > df['MACD_signal'].iloc[i] and df['MACD'].iloc[i-1] <= df['MACD_signal'].iloc[i-1]

# --- Sell signals ---
def sell_profit_target(df, i, entry_price, target=0.02):
    return (df['close'].iloc[i] - entry_price) / entry_price >= target

def sell_rsi_overbought(df, i, entry_price=None):
    return df['RSI'].iloc[i] > 70

def sell_macd_cross_down(df, i, entry_price=None):
    return df['MACD'].iloc[i] < df['MACD_signal'].iloc[i] and df['MACD'].iloc[i-1] >= df['MACD_signal'].iloc[i-1]

# --- Backtest all buy/sell combinations ---
buy_signals = [buy_sma_cross, buy_rsi_oversold, buy_macd_cross]
sell_signals = [sell_profit_target, sell_rsi_overbought, sell_macd_cross_down]

results = []

for buy_signal in buy_signals:
    for sell_signal in sell_signals:
        position = False
        entry_price = 0
        profits = []
        trades = 0
        for i in range(1, len(df)):
            if not position and buy_signal(df, i):
                position = True
                entry_price = df['close'].iloc[i]
            elif position and sell_signal(df, i, entry_price):
                profit = (df['close'].iloc[i] - entry_price) / entry_price
                profits.append(profit)
                trades += 1
                position = False
        total_profit = sum(profits)
        avg_profit = total_profit / trades if trades > 0 else 0
        results.append({
            'buy_signal': buy_signal.__name__,
            'sell_signal': sell_signal.__name__,
            'total_profit': total_profit,
            'trades': trades,
            'avg_profit': avg_profit
        })

# Sort and display results
results = sorted(results, key=lambda x: x['total_profit'], reverse=True)

print("Backtest Results (sorted by total profit):\n")
for r in results:
    print(f"Buy Signal: {r['buy_signal']:20} | Sell Signal: {r['sell_signal']:20} | "
          f"Total Profit: {r['total_profit']*100:.2f}% | Trades: {r['trades']} | Avg Profit: {r['avg_profit']*100:.2f}%")
