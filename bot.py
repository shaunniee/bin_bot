import os
import numpy as np
import pandas as pd
from binance.client import Client

# Get API keys from environment variables
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Connect to Binance Testnet
client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'  # Binance Testnet base URL

def get_historical_data(symbol, interval, lookback):
    klines = client.get_historical_klines(symbol, interval, lookback)
    data = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    data['close'] = data['close'].astype(float)
    return data

def compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_macd(prices, fast=12, slow=26, signal=9):
    fast_ema = prices.ewm(span=fast, adjust=False).mean()
    slow_ema = prices.ewm(span=slow, adjust=False).mean()
    macd = fast_ema - slow_ema
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd - signal_line

def buy_rsi(data):
    rsi = compute_rsi(data['close'])
    return 1 if rsi.iloc[-1] < 30 else 0

def buy_macd(data):
    macd_val = compute_macd(data['close'])
    return 1 if macd_val.iloc[-1] > 0 else 0

def sell_rsi(data):
    rsi = compute_rsi(data['close'])
    return 1 if rsi.iloc[-1] > 70 else 0

def sell_macd(data):
    macd_val = compute_macd(data['close'])
    return 1 if macd_val.iloc[-1] < 0 else 0

buy_funcs = [buy_rsi, buy_macd]
sell_funcs = [sell_rsi, sell_macd]

def backtest_strategy(buy_weights, sell_weights):
    data = get_historical_data("BTCUSDT", "1h", "30 day ago UTC")
    balance = 1.0
    position = 0
    entry_price = 0
    trades = 0
    profit_pct_list = []

    for i in range(15, len(data)):
        window = data.iloc[:i+1]
        buy_score = sum(w * f(window) for w, f in zip(buy_weights, buy_funcs))
        sell_score = sum(w * f(window) for w, f in zip(sell_weights, sell_funcs))

        buy_score /= sum(buy_weights) if sum(buy_weights) != 0 else 1
        sell_score /= sum(sell_weights) if sum(sell_weights) != 0 else 1

        price = data.iloc[i]['close']

        if buy_score > 0.5 and position == 0:
            position = 1
            entry_price = price
        elif sell_score > 0.5 and position == 1:
            position = 0
            exit_price = price
            trades += 1
            profit_pct = (exit_price - entry_price) / entry_price
            balance *= (1 + profit_pct)
            profit_pct_list.append(profit_pct)

    total_profit = balance - 1
    avg_profit = np.mean(profit_pct_list) if profit_pct_list else 0
    return total_profit, trades, avg_profit

# GA parameters
POP_SIZE = 60
GENERATIONS = 40
N_BUY = len(buy_funcs)
N_SELL = len(sell_funcs)
LOWER, UPPER = 0, 1

def init_population():
    return np.random.uniform(LOWER, UPPER, size=(POP_SIZE, N_BUY + N_SELL))

def fitness(individual):
    buy_weights = individual[:N_BUY]
    sell_weights = individual[N_BUY:]
    profit, trades, avg_profit = backtest_strategy(buy_weights, sell_weights)
    if trades < 3:
        return -1000  # Penalize but not -inf
    return profit + 0.1 * avg_profit  # Mix profit and avg profit

def select(pop, fitnesses):
    selected = []
    for _ in range(POP_SIZE):
        i, j = np.random.choice(range(POP_SIZE), 2, replace=False)
        winner = i if fitnesses[i] > fitnesses[j] else j
        selected.append(pop[winner])
    return np.array(selected)

def crossover(parent1, parent2):
    child = np.array([parent1[i] if np.random.rand() > 0.5 else parent2[i] for i in range(len(parent1))])
    return child, child.copy()

def mutate(individual, mutation_rate=0.3):
    for i in range(len(individual)):
        if np.random.rand() < mutation_rate:
            individual[i] = np.clip(individual[i] + np.random.normal(0, 0.1), LOWER, UPPER)
    return individual

def genetic_algorithm():
    population = init_population()

    for gen in range(GENERATIONS):
        fitnesses = np.array([fitness(ind) for ind in population])
        best_idx = np.argmax(fitnesses)
        print(f"Generation {gen+1} - Best profit: {fitnesses[best_idx]:.4f}")

        selected = select(population, fitnesses)
        next_population = []

        # Keep best individual (elitism)
        next_population.append(population[best_idx].copy())

        # Add a random new individual for diversity
        next_population.append(np.random.uniform(LOWER, UPPER, size=N_BUY + N_SELL))

        for i in range(2, POP_SIZE, 2):
            p1, p2 = selected[i], selected[i+1]
            c1, c2 = crossover(p1, p2)
            next_population.append(mutate(c1))
            if len(next_population) < POP_SIZE:
                next_population.append(mutate(c2))

        population = np.array(next_population[:POP_SIZE])

    fitnesses = np.array([fitness(ind) for ind in population])
    best_idx = np.argmax(fitnesses)
    best_weights = population[best_idx]

    print("\nBest Buy Weights:", best_weights[:N_BUY])
    print("Best Sell Weights:", best_weights[N_BUY:])

    profit, trades, avg_profit = backtest_strategy(best_weights[:N_BUY], best_weights[N_BUY:])
    print(f"Final Results: Profit={profit*100:.2f}%, Trades={trades}, Avg Profit per trade={avg_profit*100:.2f}%")

if __name__ == "__main__":
    genetic_algorithm()
