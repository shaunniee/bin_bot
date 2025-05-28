import os
import pandas as pd
import numpy as np
import requests
from itertools import product
import ta  # You need to install ta-lib or use `pip install ta`

# --- Binance Testnet historical data fetch ---
def get_binance_testnet_klines(symbol, interval, limit=1000):
    base_url = 'https://testnet.binance.vision/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    response = requests.get(base_url, params=params)
    data = response.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    df = df.astype({
        'open': 'float', 'high': 'float', 'low': 'float', 'close': 'float', 'volume': 'float'
    })
    return df[['open', 'high', 'low', 'close', 'volume']]

# --- Add indicators ---
def add_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['ema9'] = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator()
    df['ema21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close'])/3).cumsum() / df['volume'].cumsum()
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()
    df.dropna(inplace=True)
    return df

# --- Buy and sell signals with separate weights ---
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

# --- Backtest the strategy with given weights ---
def backtest_strategy(df, buy_weights, sell_weights):
    usdt = 1000
    position = 0
    entry_price = 0
    trades = 0

    for i in range(1, len(df)):
        row = df.iloc[i]
        if position == 0 and buy_signal(row, buy_weights):
            position = usdt / row['close']
            entry_price = row['close']
            trades += 1
        elif position > 0 and sell_signal(row, sell_weights):
            usdt = position * row['close']
            position = 0
            trades += 1

    # Close position if still open at the end
    if position > 0:
        usdt = position * df.iloc[-1]['close']

    profit = usdt - 1000
    return profit

# --- Optimize weights by brute force ---
def optimize_weights(df):
    best_profit = float('-inf')
    best_buy_weights = None
    best_sell_weights = None
    weight_range = [0, 1, 2]

    total_combinations = len(weight_range)**6 * len(weight_range)**6
    print(f"Total combinations to test: {total_combinations}")

    count = 0
    for buy_weights in product(weight_range, repeat=6):
        for sell_weights in product(weight_range, repeat=6):
            profit = backtest_strategy(df, buy_weights, sell_weights)
            count += 1
            if profit > best_profit:
                best_profit = profit
                best_buy_weights = buy_weights
                best_sell_weights = sell_weights
                print(f"New Best -> Profit: {profit:.2f}, Buy weights: {buy_weights}, Sell weights: {sell_weights}")
            if count % 1000 == 0:
                print(f"Tested {count}/{total_combinations} combinations...")

    print(f"\nBest Buy weights: {best_buy_weights}, Best Sell weights: {best_sell_weights}, Max Profit: {best_profit:.2f}")
    return best_buy_weights, best_sell_weights

def main():
    print("Fetching historical data...")
    df = get_binance_testnet_klines('XRPUSDT', '15m', limit=1000)
    print("Calculating indicators...")
    df = add_indicators(df)
    print("Optimizing weights, this may take some time...")
    best_buy_weights, best_sell_weights = optimize_weights(df)
    print("Backtesting using best weights...")
    final_profit = backtest_strategy(df, best_buy_weights, best_sell_weights)
    print(f"Final profit with best weights: {final_profit:.2f}")

if __name__ == "__main__":
    main()
