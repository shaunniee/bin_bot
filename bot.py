import requests
import pandas as pd
import time
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
import os

# --- CONFIGURATION ---
symbol = "XRPUSDT"
interval = "15m"
days = 730  # approx 2 years
limit_per_request = 1000
initial_balance = 10000
data_file = f"{symbol}_{interval}_{days}d.csv"

strategies = ["BREAKOUT_RETEST", "SCALPING_VWAP", "EMA_RSI_VWAP"]  # added EMA_RSI_VWAP to list

# --- FETCH BINANCE KLINES ---
def get_klines(symbol, interval, start_time, end_time, limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
        "startTime": start_time,
        "endTime": end_time
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data

def fetch_data(symbol, interval, days):
    if os.path.exists(data_file):
        print(f"Loading cached data from {data_file}")
        df = pd.read_csv(data_file, index_col=0, parse_dates=True)
        return df

    print(f"Fetching {days} days of data for {symbol} @ {interval}...")

    end_time = int(time.time() * 1000)
    start_time = end_time - days * 24 * 60 * 60 * 1000
    all_klines = []

    total_klines_needed = days * 24 * 4  # 4 x 15min intervals per hour
    fetched_klines = 0

    while start_time < end_time:
        klines = get_klines(symbol, interval, start_time, end_time, limit_per_request)
        if not klines:
            break
        all_klines += klines
        fetched_klines += len(klines)
        start_time = klines[-1][0] + 1

        progress = (fetched_klines / total_klines_needed) * 100
        print(f"Progress: {progress:.2f}% ({fetched_klines} klines fetched)", end='\r')

        time.sleep(0.25)  # rate limit

        if len(klines) < limit_per_request:
            break  # no more data

    print("\nFinished fetching data.")

    df = pd.DataFrame(all_klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # Save for later use
    df.to_csv(data_file)
    print(f"Saved data to {data_file}")

    return df

# --- MANUAL VWAP ---
def add_vwap(df, window=14):
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    pv = typical_price * df['volume']
    vwap = pv.rolling(window=window).sum() / df['volume'].rolling(window=window).sum()
    df['vwap'] = vwap
    return df

# --- INDICATORS ---
def add_indicators(df):
    df["ema9"] = EMAIndicator(df["close"], window=9).ema_indicator()
    df["ema21"] = EMAIndicator(df["close"], window=21).ema_indicator()
    df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
    df = add_vwap(df)
    return df

# --- STRATEGIES ---
def strategy_ema_rsi_vwap(row, prev_row):
    if prev_row is None:
        return False
    price_cross_vwap = (prev_row["close"] < prev_row["vwap"]) and (row["close"] > row["vwap"])
    ema_cross = (prev_row["ema9"] < prev_row["ema21"]) and (row["ema9"] > row["ema21"])
    rsi_cross = (prev_row["rsi"] < 30) and (row["rsi"] > 30)
    return price_cross_vwap and ema_cross and rsi_cross

def strategy_breakout_retest(df, idx):
    if idx < 13:
        return False
    window = df.iloc[idx-13:idx-1]
    resistance = window["high"].max()
    current = df.iloc[idx]
    prev = df.iloc[idx-1]
    breakout = (prev["close"] <= resistance) and (current["close"] > resistance)
    retest = (idx + 1 < len(df)) and (df.iloc[idx+1]["low"] >= resistance)
    return breakout and retest

def strategy_scalping_vwap(row, prev_row):
    if prev_row is None:
        return False
    bounce = (row["low"] <= row["vwap"] * 1.002) and (row["close"] > row["vwap"])
    rsi_good = 40 <= row["rsi"] <= 60
    return bounce and rsi_good

# --- BACKTEST ---
def backtest_strategy(df, strategy_name, stop_loss_pct, take_profit_pct):
    balance = initial_balance
    position = 0
    buy_price = 0
    trade_log = []

    sl_hits = 0
    tp_hits = 0
    profit_sl_hits = 0
    loss_sl_hits = 0

    trailing_sl_price = None

    monthly_profits = {}

    for i in range(1, len(df) - 1):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        # Get signal based on strategy
        signal = False
        if strategy_name == "EMA_RSI_VWAP":
            signal = strategy_ema_rsi_vwap(row, prev_row)
        elif strategy_name == "BREAKOUT_RETEST":
            signal = strategy_breakout_retest(df, i)
        elif strategy_name == "SCALPING_VWAP":
            signal = strategy_scalping_vwap(row, prev_row)

        if position == 0 and signal:
            # Enter position (buy)
            buy_price = row["close"]
            position = balance / buy_price
            balance = 0
            trailing_sl_price = buy_price * (1 - stop_loss_pct)
            trade_log.append({"time": df.index[i], "type": "BUY", "price": buy_price})

        elif position > 0:
            current_price = row["close"]

            # Update trailing stop loss only if price moves up
            price_move_pct = (current_price - buy_price) / buy_price
            # Set trailing stop to max of current trailing_sl_price and (current_price - stop_loss_pct)
            new_trailing_sl = current_price * (1 - stop_loss_pct)
            if new_trailing_sl > trailing_sl_price:
                trailing_sl_price = new_trailing_sl

            # Take Profit Check
            if current_price >= buy_price * (1 + take_profit_pct):
                balance = position * current_price
                profit = (current_price - buy_price) * position
                month = df.index[i].strftime("%Y-%m")
                monthly_profits[month] = monthly_profits.get(month, 0) + profit
                trade_log.append({"time": df.index[i], "type": "SELL_TP", "price": current_price, "profit": profit})
                position = 0
                tp_hits += 1
                trailing_sl_price = None

            # Stop Loss Check (Trailing)
            elif current_price <= trailing_sl_price:
                balance = position * current_price
                profit = (current_price - buy_price) * position
                month = df.index[i].strftime("%Y-%m")
                monthly_profits[month] = monthly_profits.get(month, 0) + profit
                trade_log.append({"time": df.index[i], "type": "SELL_SL", "price": current_price, "profit": profit})

                sl_hits += 1
                if current_price > buy_price:
                    profit_sl_hits += 1
                else:
                    loss_sl_hits += 1

                position = 0
                trailing_sl_price = None

    # Close any open position at the end of data
    if position > 0:
        last_price = df["close"].iloc[-1]
        balance = position * last_price
        profit = (last_price - buy_price) * position
        month = df.index[-1].strftime("%Y-%m")
        monthly_profits[month] = monthly_profits.get(month, 0) + profit
        trade_log.append({"time": df.index[-1], "type": "SELL_EOD", "price": last_price, "profit": profit})
        position = 0

    return balance, trade_log, sl_hits, tp_hits, profit_sl_hits, loss_sl_hits, monthly_profits


# --- MAIN ---
def main():
    df = fetch_data(symbol, interval, days)
    print(f"Data loaded: {len(df)} rows")

    df = add_indicators(df)
    print("Indicators added.")

    # Example: Manually specify SL and TP here, or loop over ranges
    user_stop_loss = 0.01  # 2%
    user_take_profit = 0.01  # 5%

    for strat in strategies:
        print(f"\nRunning strategy: {strat}")
        final_balance, trades, sl_hits, tp_hits, profit_sl_hits, loss_sl_hits, monthly_profits = backtest_strategy(
            df, strat, user_stop_loss, user_take_profit
        )
        net_return_pct = ((final_balance - initial_balance) / initial_balance) * 100
        num_trades = len([t for t in trades if t["type"] == "BUY"])

        print(f"Stop Loss: {user_stop_loss*100:.2f}%, Take Profit: {user_take_profit*100:.2f}%")
        print(f"Trades: {num_trades}")
        print(f"SL Hits: {sl_hits}, TP Hits: {tp_hits}")
        print(f"Profit on SL Hits: {profit_sl_hits}, Loss on SL Hits: {loss_sl_hits}")
        print(f"Final balance: ${final_balance:.2f} (Net Return: {net_return_pct:.2f}%)")

        # Optional: print trades summary
        # for t in trades:
        #     print(t)

        # Monthly profit summary
        print("Monthly Profits:")
        for month, profit in sorted(monthly_profits.items()):
            print(f"{month}: {profit:.2f}")

if __name__ == "__main__":
    main()
