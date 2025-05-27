import os
import asyncio
import time
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
TRADE_PERCENTAGE = 0.99
PROFIT_TARGET = 0.025
STOP_LOSS_PERCENTAGE = 0.025
COOLDOWN_SECONDS = 43200

# === INIT ===
client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'
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

async def wait_for_filled_order(order_id):
    while True:
        order = client.get_order(symbol=SYMBOL, orderId=order_id)
        if order['status'] == 'FILLED':
            return order
        await asyncio.sleep(2)

async def place_order(side, quantity):
    order = client.create_order(
        symbol=SYMBOL,
        side=SIDE_BUY if side == "Buy" else SIDE_SELL,
        type=ORDER_TYPE_MARKET,
        quantity=quantity
    )
    filled_order = await wait_for_filled_order(order['orderId'])

    trades = client.get_my_trades(symbol=SYMBOL)
    recent_trades = [t for t in trades if t['orderId'] == order['orderId']]
    executed_qty = sum(float(t['qty']) for t in recent_trades)
    total_cost = sum(float(t['qty']) * float(t['price']) for t in recent_trades)
    fee = sum(float(t['commission']) for t in recent_trades)
    commission_asset = recent_trades[0]['commissionAsset'] if recent_trades else 'N/A'
    avg_price = total_cost / executed_qty if executed_qty else 0

    return {
        "executed_qty": executed_qty,
        "avg_price": avg_price,
        "total_cost": total_cost,
        "fee": fee,
        "commission_asset": commission_asset,
        "order": filled_order
    }

def get_last_buy_price_if_balance_high(symbol="XRPUSDT", asset="XRP", min_qty=10):
    balance = get_balance(asset)
    if balance >= min_qty:
        trades = client.get_my_trades(symbol=symbol)
        for trade in reversed(trades):
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
            btc_balance = get_balance("BTC")
            eth_balance = get_balance("ETH")
            usdt_balance = get_balance("USDT")
            xrp_value = xrp_balance * current_price
            btc_value = btc_balance * current_price
            eth_value = eth_balance * current_price
            total_value = usdt_balance + xrp_value + btc_value + eth_value

            ticker_24hr = client.get_ticker(symbol=SYMBOL)
            price_change_percent = float(ticker_24hr['priceChangePercent'])

            if xrp_balance >= 10:
                buy_price = get_last_buy_price_if_balance_high()
            else:
                buy_price = 0

            change_from_buy = ((current_price - buy_price) / buy_price * 100) if buy_price else None

            log_msg = (
                f"{now} | 📊 Market Check\n"
                f"🔹 Current Price: {current_price:.4f} USDT\n"
                f"📉 24hr Change: {price_change_percent:.2f}%\n"
                f"💰 USDT Balance: {usdt_balance:.2f}\n"
                f"💎 XRP Balance: {xrp_balance:.2f} (~{xrp_value:.2f} USDT)\n"
                f"💎 BTC Balance: {btc_balance:.2f} (~{btc_value:.2f} USDT)\n"
                f"💎 ETH Balance: {eth_balance:.2f} (~{eth_value:.2f} USDT)\n"
                f"💼 Total Value: {total_value:.2f} USDT\n"
            )
            client.create_order(symbol="BTCUSDT",side=SIDE_SELL,type=ORDER_TYPE_MARKET,quantity=0.08)
            client.create_order(symbol="ETHUSDT",side=SIDE_SELL,type=ORDER_TYPE_MARKET,quantity=0.77)
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
                        order_info = await place_order("Sell", qty)
                        status = "📈 Sold XRP (Profit)" if price_change >= PROFIT_TARGET else "🔻 Stop-loss hit. Sold XRP"
                        await send_telegram(
                            f"{status}\n"
                            f"🔹 Quantity: {order_info['executed_qty']:.2f}\n"
                            f"💰 Avg Price: {order_info['avg_price']:.4f} USDT\n"
                            f"💸 Fee: {order_info['fee']} {order_info['commission_asset']}"
                        )
                        buy_price = None
                        if price_change <= -STOP_LOSS_PERCENTAGE:
                            cooldown_start = time.time()
                            in_cooldown = True

            # === BUY LOGIC ===
            else:
                if price_change_percent <= -2.5:
                    if usdt_balance >= 10:
                        trade_usdt = usdt_balance * TRADE_PERCENTAGE
                        qty = round_step_size(trade_usdt / current_price, lot_size)
                        order_info = await place_order("Buy", qty)
                        buy_price = order_info['avg_price']
                        await send_telegram(
                            f"🛒 Bought XRP\n"
                            f"🔹 Quantity: {order_info['executed_qty']:.2f}\n"
                            f"💰 Avg Price: {order_info['avg_price']:.4f} USDT\n"
                            f"💸 Fee: {order_info['fee']} {order_info['commission_asset']}"
                        )
                    else:
                        print(f"{now} | Skipping buy: USDT too low (${usdt_balance:.2f})")
                else:
                    print(f"{now} | Skipping buy: 24hr price drop is only {price_change_percent:.2f}%")

        except Exception as e:
            print(f"Error: {e}")
            await send_telegram(f"⚠️ Error occurred: {e}")

        await asyncio.sleep(600)

# Run the trading loop
asyncio.run(trading_loop())
