import os
import pandas as pd
from binance.client import Client
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands
from ta.volume import VolumeWeightedAveragePrice

# --- Load environment variables for Binance Testnet API ---
API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")

client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'

# --- Fetch historical data from Binance ---
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

# --- Signal logic ---
def buy_signal(row, weights):
    score = 0
    score += weights[0] * (row['rsi'] < 30)
    score += weights[1] * (row['macd'] > row['macd_signal'])
    score += weights[2] * (row['ema9'] > row['ema21'])
    score += weights[3] * (row['close'] > row['vwap'])
    score += weights[4] * (row['close'] < row['bb_lower'])
    score += weights[5] * (row['stoch_k'] < 20 and row['stoch_k'] > row['stoch_d'])
    return score >= 3

def sell_signal(row, weights):
    score = 0
    score += weights[0] * (row['rsi'] > 70)
    score += weights[1] * (row['macd'] < row['macd_signal'])
    score += weights[2] * (row['ema9'] < row['ema21'])
    score += weights[3] * (row['close'] < row['vwap'])
    score += weights[4] * (row['close'] > row['bb_upper'])
    score += weights[5] * (row['stoch_k'] > 80 and row['stoch_k'] < row['stoch_d'])
    return score >= 3

# --- Backtest strategy ---
def backtest_strategy(df, weights):
    usdt = 1000
    position = 0
    for i in range(1, len(df)):
        row = df.iloc[i]
        if position == 0 and buy_signal(row, weights):
            position = usdt / row['close']
            buy_price = row['close']
            print(f"Buy @ {buy_price:.2f}")
        elif position > 0 and sell_signal(row, weights):
            usdt = position * row['close']
            print(f"Sell @ {row['close']:.2f}, Profit: {usdt - 1000:.2f}")
            position = 0

    if position > 0:
        usdt = position * df.iloc[-1]['close']
        print(f"Final Sell @ {df.iloc[-1]['close']:.2f}, Final Profit: {usdt - 1000:.2f}")

# --- Main logic ---
if __name__ == "__main__":
    df = get_klines('BTCUSDT', '1h', 1000)
    df = add_indicators(df)
    weights = [1, 1, 1, 1, 1, 1]  # You can optimize these
    backtest_strategy(df, weights)
