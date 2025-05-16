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

async def send_telegram(msg):
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

def get_price():
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    return float(ticker['price'])

def get_balance(asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free'])

def place_order(side, quantity):
    return client.order_limit(
        symbol=SYMBOL,
        side=SIDE_BUY if side == "Buy" else SIDE_SELL,
        quantity=quantity,
        price=str(get_price())
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
                    await send_telegram("Cooldown ended. Resuming trades.")
                else:
                    print(f"{now} | In cooldown. Waiting...")
                    await asyncio.sleep(600)
                    continue

            current_price = get_price()
            print(f"{now} | Price: {current_price:.4f}")

            if buy_price:
                price_change = (current_price - buy_price) / buy_price

                if price_change >= PROFIT_TARGET:
                    xrp_balance = get_balance("XRP")
                    if xrp_balance > 0:
                        place_order("Sell", round(xrp_balance, 2))
                        await send_telegram(f"📈 Sold XRP at {current_price:.4f} (Profit)")
                        buy_price = None

                elif price_change <= -STOP_LOSS_PERCENTAGE:
                    xrp_balance = get_balance("XRP")
                    if xrp_balance > 0:
                        place_order("Sell", round(xrp_balance, 2))
                        await send_telegram(f"🔻 Stop-loss hit. Sold XRP at {current_price:.4f}")
                        buy_price = None
                        cooldown_start = time.time()
                        in_cooldown = True

            else:
                usdt_balance = get_balance("USDT")
                if usdt_balance >= 10:
                    trade_usdt = usdt_balance * TRADE_PERCENTAGE
                    qty = round(trade_usdt / current_price, 2)
                    place_order("Buy", qty)
                    buy_price = current_price
                    await send_telegram(f"🛒 Bought XRP at {current_price:.4f}")
                else:
                    print(f"{now} | Skipping buy: USDT too low (${usdt_balance:.2f})")

        except Exception as e:
            print(f"Error: {e}")

        await asyncio.sleep(600)  # Wait 10 minutes

# Run the trading loop
asyncio.run(trading_loop())
