import os
import time
import asyncio
from binance.client import Client
from binance.enums import *
from telegram import Bot
from datetime import datetime

# === CONFIGURATION ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "XRPUSDT"
TRADE_PERCENTAGE = 0.98
PROFIT_TARGET = 0.03
STOP_LOSS_PERCENTAGE = 0.03
COOLDOWN_SECONDS = 86400  # 24 hours

# === INIT ===
client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'  # Use Binance Spot Testnet
bot = Bot(token=TELEGRAM_TOKEN)
in_cooldown = False

# === PRECISION HANDLING ===
symbol_info = client.get_symbol_info(SYMBOL)

def round_step_size(value, step_size):
    return round(value - (value % step_size), 8)

def get_lot_size():
    for f in symbol_info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.01

def get_tick_size():
    for f in symbol_info['filters']:
        if f['filterType'] == 'PRICE_FILTER':
            return float(f['tickSize'])
    return 0.0001

lot_size = get_lot_size()
tick_size = get_tick_size()

# === UTILS ===
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_price():
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    return float(ticker['price'])

def get_balance(asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free'])

def place_order(side, quantity, price):
    return client.create_order(
        symbol=SYMBOL,
        side=SIDE_BUY if side == "Buy" else SIDE_SELL,
        type=ORDER_TYPE_LIMIT,
        timeInForce=TIME_IN_FORCE_GTC,
        quantity=quantity,
        price=price
    )

def get_last_buy_price_if_balance_high(symbol="XRPUSDT", asset="XRP", min_qty=10):
    balance = get_balance(asset)
    if balance >= min_qty:
        trades = client.get_my_trades(symbol=symbol)
        for trade in reversed(trades):  # Most recent first
            if trade['isBuyer']:
                return float(trade['price'])
    return None

# === TRADING LOOP ===
buy_price = None
cooldown_start = None

async def trading_loop():
    global buy_price, cooldown_start, in_cooldown

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if in_cooldown:
                if time.time() - cooldown_start >= COOLDOWN_SECONDS:
                    in_cooldown = False
                    await send_telegram("✅ Cooldown ended. Resuming trades.")
                else:
                    print(f"{now} | In cooldown. Waiting...")
                    await asyncio.sleep(600)
                    continue

            current_price = get_price()
            print(f"{now} | Price: {current_price:.4f}")

            # Check XRP balance and reset buy_price if needed
            xrp_balance = get_balance("XRP")
            if xrp_balance >= 10:
                buy_price = get_last_buy_price_if_balance_high()
                if buy_price:
                    print(f"{now} | 📌 Last buy price (XRP > 10): {buy_price:.4f}")
            else:
                buy_price = 0
                print(f"{now} | XRP balance is below 10. Resetting buy_price to 0.")

            if buy_price:
                price_change = (current_price - buy_price) / buy_price

                if price_change >= PROFIT_TARGET or price_change <= -STOP_LOSS_PERCENTAGE:
                    if xrp_balance > 0:
                        qty = round_step_size(xrp_balance, lot_size)
                        price = round_step_size(current_price, tick_size)
                        place_order("Sell", qty, str(price))
                        status = "📈 Sold XRP (Profit)" if price_change >= PROFIT_TARGET else "🔻 Stop-loss hit. Sold XRP"
                        await send_telegram(f"{status} at {price:.4f}")
                        buy_price = None
                        if price_change <= -STOP_LOSS_PERCENTAGE:
                            cooldown_start = time.time()
                            in_cooldown = True

            else:
                usdt_balance = get_balance("USDT")
                ticker_24hr = client.get_ticker(symbol=SYMBOL)
                price_change_percent = float(ticker_24hr['priceChangePercent'])

                print(f"{now} | 24hr Change: {price_change_percent:.2f}%")

                if price_change_percent <= -5:
                    if usdt_balance >= 10:
                        trade_usdt = usdt_balance * TRADE_PERCENTAGE
                        qty = round_step_size(trade_usdt / current_price, lot_size)
                        price = round_step_size(current_price, tick_size)
                        place_order("Buy", qty, str(price))
                        buy_price = current_price
                        await send_telegram(f"🛒 Bought XRP at {price:.4f} after 24hr drop of {price_change_percent:.2f}%")
                    else:
                        print(f"{now} | Skipping buy: USDT too low (${usdt_balance:.2f})")
                else:
                    print(f"{now} | Skipping buy: 24hr price drop is only {price_change_percent:.2f}%")

        except Exception as e:
            print(f"Error: {e}")
            await send_telegram(f"⚠️ Error occurred: {e}")

        await asyncio.sleep(600)  # Wait 10 minutes

# Run the trading loop
asyncio.run(trading_loop())
