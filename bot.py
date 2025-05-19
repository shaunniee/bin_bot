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

lot_size = get_lot_size()

# === UTILS ===
async def send_telegram(msg):
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

def get_price():
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    return float(ticker['price'])

def get_balance(asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free'])

def place_order(side, quantity):
    return client.create_order(
        symbol=SYMBOL,
        side=SIDE_BUY if side == "Buy" else SIDE_SELL,
        type=ORDER_TYPE_MARKET,
        quantity=quantity
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
            xrp_balance = get_balance("XRP")
            usdt_balance = get_balance("USDT")
            xrp_value = xrp_balance * current_price
            total_value = usdt_balance + xrp_value

            ticker_24hr = client.get_ticker(symbol=SYMBOL)
            price_change_percent = float(ticker_24hr['priceChangePercent'])

            if xrp_balance >= 10:
                buy_price = get_last_buy_price_if_balance_high()
            else:
                buy_price = 0

            change_from_buy = ((current_price - buy_price) / buy_price * 100) if buy_price else None

            # === LOGGING AND TELEGRAM UPDATE ===
            log_msg = (
                f"{now} | 📊 Market Check\n"
                f"🔹 Current Price: {current_price:.4f} USDT\n"
                f"📉 24hr Change: {price_change_percent:.2f}%\n"
                f"💰 USDT Balance: {usdt_balance:.2f}\n"
                f"💎 XRP Balance: {xrp_balance:.2f} (~{xrp_value:.2f} USDT)\n"
                f"💼 Total Value: {total_value:.2f} USDT\n"
            )
            if buy_price:
                log_msg += f"🛒 Buy Price: {buy_price:.4f} | Change Since Buy: {change_from_buy:.2f}%\n"

            print(log_msg)
            await send_telegram(log_msg)

            # === SELL LOGIC ===
            if buy_price:
                price_change = (current_price - buy_price) / buy_price

                if price_change >= PROFIT_TARGET or price_change <= -STOP_LOSS_PERCENTAGE:
                    if xrp_balance > 0:
                        qty = round_step_size(xrp_balance, lot_size)
                        place_order("Sell", qty)
                        status = "📈 Sold XRP (Profit)" if price_change >= PROFIT_TARGET else "🔻 Stop-loss hit. Sold XRP"
                        await send_telegram(f"{status} at {current_price:.4f}")
                        buy_price = None
                        if price_change <= -STOP_LOSS_PERCENTAGE:
                            cooldown_start = time.time()
                            in_cooldown = True

            # === BUY LOGIC ===
            else:
                if price_change_percent <= -3:
                    if usdt_balance >= 10:
                        trade_usdt = usdt_balance * TRADE_PERCENTAGE
                        qty = round_step_size(trade_usdt / current_price, lot_size)
                        place_order("Buy", qty)
                        buy_price = current_price
                        await send_telegram(f"🛒 Bought XRP at {current_price:.4f} after 24hr drop of {price_change_percent:.2f}%")
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
