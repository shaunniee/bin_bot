import os
import pandas as pd
from itertools import product
from binance.client import Client
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands
from ta.volume import VolumeWeightedAveragePrice

# --- Load Binance Testnet API keys from environment ---
API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")

client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'

# --- Fetch historical klines from Binance Testnet ---
def get_klines(symbol='BTCUSDT', interval='1h', limit=1000):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

# --- Add technical indicators ---
def add_indicators(df):
    df['rsi'] = RSIIndicator(df['close']).rsi()
    macd = MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['ema9'] = EMAIndicator(df['close'], window=9).ema_indicator()
    df['ema21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    vwap = VolumeWeightedAveragePrice(high=df['high'], low=df['low'], close=df['close'], volume=df['volume'])
    df['vwap'] = vwap.volume_weighted_average_price()
    bb = BollingerBands(close=df['close'])
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    stoch = StochasticOscillator(df['high'], df['low'], df['close'])
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()
    df.dropna(inplace=True)
    return df

# --- Buy signal based on weighted indicators ---
def buy_signal(row, weights):
    score = 0
    score += weights[0] * (row['rsi'] < 30)
    score += weights[1] * (row['macd'] > row['macd_signal'])
    score += weights[2] * (row['ema9'] > row['ema21'])
    score += weights[3] * (row['close'] > row['vwap'])
    score += weights[4] * (row['close'] < row['bb_lower'])
    score += weights[5] * (row['stoch_k'] < 20 and row['stoch_k'] > row['stoch_d'])
    return score >= 3

# --- Sell signal based on weighted indicators ---
def sell_signal(row, weights):
    score = 0
    score += weights[0] * (row['rsi'] > 70)
    score += weights[1] * (row['macd'] < row['macd_signal'])
    score += weights[2] * (row['ema9'] < row['ema21'])
    score += weights[3] * (row['close'] < row['vwap'])
    score += weights[4] * (row['close'] > row['bb_upper'])
    score += weights[5] * (row['stoch_k'] > 80 and row['stoch_k'] < row['stoch_d'])
    return score >= 3

# --- Backtest strategy with detailed logs ---
def backtest_strategy(df, weights):
    usdt = 1000
    position = 0
    entry_price = 0
    trades = 0
    for i in range(1, len(df)):
        row = df.iloc[i]
        if position == 0 and buy_signal(row, weights):
            position = usdt / row['close']
            entry_price = row['close']
            print(f"Bought at {entry_price:.2f} on {row.name}")
            trades += 1
        elif position > 0 and sell_signal(row, weights):
            usdt = position * row['close']
            profit = usdt - 1000
            print(f"Sold at {row['close']:.2f} on {row.name}, Profit: {profit:.2f}")
            position = 0
            trades += 1
    # Close any open position at last price
    if position > 0:
        usdt = position * df.iloc[-1]['close']
        print(f"Closing remaining position at {df.iloc[-1]['close']:.2f}")
    profit = usdt - 1000
    print(f"Total trades: {trades}, Final profit: {profit:.2f}")
    return profit

# --- Find best weights by brute force ---
def optimize_weights(df):
    best_profit = float('-inf')
    best_weights = None
    # Use weights 0,1,2 for each indicator (6 indicators)
    for weights in product([0, 1, 2], repeat=6):
        profit = backtest_strategy(df, weights)
        if profit > best_profit:
            best_profit = profit
            best_weights = weights
            print(f"New Best -> Profit: {profit:.2f}, Weights: {weights}")
    print(f"\nBest Weights: {best_weights}, Max Profit: {best_profit:.2f}")
    return best_weights

# --- Main execution ---
if __name__ == "__main__":
    print("Fetching historical data...")
    df = get_klines('BTCUSDT', '1h', 1000)
    print("Adding indicators...")
    df = add_indicators(df)
    print("Optimizing weights...")
    best_weights = optimize_weights(df)
    print("\nBacktesting using best weights:")
    final_profit = backtest_strategy(df, best_weights)
    print(f"Final Profit: {final_profit:.2f}")
