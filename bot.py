import ccxt
import pandas as pd
import matplotlib.pyplot as plt
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# ------------------------
# Fetch Historical Data
# ------------------------
def fetch_ohlcv(symbol="BTC/USDT", timeframe="5m", limit=1000):
    exchange = ccxt.binance()
    data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df

# ------------------------
# Apply Technical Indicators
# ------------------------
def apply_indicators(df):
    df["EMA9"] = EMAIndicator(close=df["close"], window=9).ema_indicator()
    df["EMA21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
    df["RSI"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["ATR"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
    df["VWAP"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum() / df["volume"].cumsum()
    df["MACD_diff"] = MACD(close=df["close"]).macd_diff()
    df["ADX"] = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14).adx()
    return df

# ------------------------
# Strategy Variants
# ------------------------

# Buy Variants
def conservative_buy(df):  # EMA cross + RSI tighter
    latest = df.iloc[-1]
    return (
        latest["EMA9"] > latest["EMA21"]
        and 45 < latest["RSI"] < 60
        and latest["close"] > latest["VWAP"]
    )

def aggressive_buy(df):  # Only EMA cross
    latest = df.iloc[-1]
    return latest["EMA9"] > latest["EMA21"]

# Sell Variants
def conservative_sell(df, entry_price):  # Exit on RSI or ATR stop
    latest = df.iloc[-1]
    return (
        latest["RSI"] > 70 or
        latest["close"] < entry_price - 1.5 * latest["ATR"]
    )

def aggressive_sell(df, entry_price):  # Exit early
    latest = df.iloc[-1]
    return (
        latest["EMA9"] < latest["EMA21"] or
        latest["MACD_diff"] < 0
    )

# ------------------------
# Backtest Engine
# ------------------------
def backtest_strategy(df, buy_func, sell_func):
    df = apply_indicators(df.copy())
    trades = []
    position = None
    equity_curve = []
    balance = 1000  # Start balance

    for i in range(50, len(df)):
        window = df.iloc[:i+1]
        price = window.iloc[-1]["close"]

        if position is None:
            if buy_func(window):
                position = {"buy_price": price, "buy_time": window.iloc[-1]["timestamp"]}
        else:
            if sell_func(window, position["buy_price"]):
                sell_price = price
                pnl = sell_price - position["buy_price"]
                balance += pnl
                trades.append({
                    "buy_time": position["buy_time"],
                    "sell_time": window.iloc[-1]["timestamp"],
                    "buy_price": position["buy_price"],
                    "sell_price": sell_price,
                    "pnl": pnl,
                    "balance": balance
                })
                position = None

        equity_curve.append(balance if position is None else balance + (price - position["buy_price"]))

    result_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame({"timestamp": df.iloc[50:]["timestamp"].values, "equity": equity_curve})
    return result_df, equity_df

# ------------------------
# Plot Results
# ------------------------
def plot_equity_curve(equity_df, label):
    plt.plot(equity_df["timestamp"], equity_df["equity"], label=label)
    plt.xlabel("Time")
    plt.ylabel("Equity (USDT)")
    plt.title("Equity Curve")
    plt.legend()

# ------------------------
# Run Multiple Strategies
# ------------------------
if __name__ == "__main__":
    df = fetch_ohlcv("BTC/USDT", timeframe="5m", limit=1000)

    buy_strategies = {
        "conservative_buy": conservative_buy,
        "aggressive_buy": aggressive_buy,
    }

    sell_strategies = {
        "conservative_sell": conservative_sell,
        "aggressive_sell": aggressive_sell,
    }

    all_results = []

    for b_name, b_func in buy_strategies.items():
        for s_name, s_func in sell_strategies.items():
            trades, equity = backtest_strategy(df, b_func, s_func)
            total_pnl = trades["pnl"].sum()
            win_rate = (trades["pnl"] > 0).sum() / len(trades) * 100 if not trades.empty else 0

            label = f"{b_name} / {s_name}"
            all_results.append((label, total_pnl, win_rate))
            print(f"\n📈 {label}")
            print(f"Trades: {len(trades)} | Total PnL: {total_pnl:.2f} | Win Rate: {win_rate:.2f}%")

            plot_equity_curve(equity, label)

    plt.tight_layout()
    plt.grid(True)
    plt.show()
