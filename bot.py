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
print(API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)


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
quantity_precision = int(symbol_info['baseAssetPrecision'])
price_precision = int(symbol_info['quoteAssetPrecision'])

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

            if buy_price:
                price_change = (current_price - buy_price) / buy_price

                if price_change >= PROFIT_TARGET or price_change <= -STOP_LOSS_PERCENTAGE:
                    xrp_balance = get_balance("XRP")
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
                xrp_balance= get_balance("XRP")
                print(usdt_balance)
                print(xrp_balance)
                if usdt_balance >= 10:
                    trade_usdt = usdt_balance * TRADE_PERCENTAGE
                    qty = round_step_size(trade_usdt / current_price, lot_size)
                    price = round_step_size(current_price, tick_size)
                    print(place_order("Buy", qty, str(price)))
                    buy_price = current_price
                    await send_telegram(f"🛒 Bought XRP at {price:.4f}")
                else:
                    print(f"{now} | Skipping buy: USDT too low (${usdt_balance:.2f})")

        except Exception as e:
            print(f"Error: {e}")
            await send_telegram(f"⚠️ Error occurred: {e}")

        await asyncio.sleep(600)  # Wait 10 minutes

# Run the trading loop
asyncio.run(trading_loop())
