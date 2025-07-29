import os
import re
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
import random
from telegram import (
    Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from dotenv import load_dotenv

import numpy as np
import pandas as pd

from price_models import random_walk
from signals import (
    load_signals, parse_text_signals,
    resample_signals_to_candles
)
from plot import (
    create_candlestick_figure,
    fig_to_html_bytes, fig_to_pdf_bytes
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === STATES ===
PRED_START_PRICE, PRED_POINTS, PRED_GAP, PRED_VOL, PRED_INTERVAL = range(5)
CHOOSING_INTERVAL, WAITING_SIGNALS = range(5, 7)

# Main menu keyboard
MAIN_MENU = ReplyKeyboardMarkup(
    [['/predict', '/chart', '/cancel']],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для предсказания цен и свечных графиков.\n"
        "Выберите команду:", reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# -------- PREDICT FLOW ----------
async def predict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "1) Введите начальную цену (например 0.01 или 0,01):",
        reply_markup=ReplyKeyboardRemove()
    )
    return PRED_START_PRICE

async def pred_start_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = re.sub(r"[^0-9.,]", "", update.message.text).replace(',', '.')
    try:
        context.user_data['start_price'] = float(txt)
    except ValueError:
        await update.message.reply_text("Неверный формат цены. Попробуйте еще раз:")
        return PRED_START_PRICE
    await update.message.reply_text("2) Сколько точек (целое число, например 50):")
    return PRED_POINTS

async def pred_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("Введите целое число точек:")
        return PRED_POINTS
    context.user_data['points'] = int(update.message.text)
    await update.message.reply_text("3) Интервал между точками в минутах (например 10):")
    return PRED_GAP

async def pred_gap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("Введите целое число минут:")
        return PRED_GAP
    context.user_data['gap'] = int(update.message.text)
    await update.message.reply_text("4) Волатильность в % (например 2 или 0.5):")
    return PRED_VOL

async def pred_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(',', '.')
    try:
        context.user_data['vol'] = float(txt) if txt else 2.0
    except ValueError:
        await update.message.reply_text("Введите число для волатильности:")
        return PRED_VOL
    # Ask timeframe for candlestick interval
    await update.message.reply_text(
        "5) Выберите интервал свечей для предсказания:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('5m', callback_data='5m'), InlineKeyboardButton('15m', callback_data='15m')],
            [InlineKeyboardButton('30m', callback_data='30m'), InlineKeyboardButton('4h', callback_data='4h')]
        ])
    )
    return PRED_INTERVAL

async def pred_interval_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    After the user selects a candle interval for /predict, this builds
    a random walk and then synthesizes 3–6 trades per point, resamples
    them into candles (with volume), and sends a candlestick chart.
    """
    q = update.callback_query
    await q.answer()
    interval = q.data
    context.user_data['interval'] = interval

    # 1) Generate the random walk
    u = context.user_data
    start_time = datetime.now()
    end_time   = start_time + timedelta(minutes=u['gap'] * (u['points'] - 1))
    df = random_walk(u['start_price'], start_time, end_time, u['points'], u['vol'])

    # 2) Build synthetic signals: 3–6 trades per point
    sigs = []
    for ts, price in zip(df['time'], df['price']):
        n_trades = random.randint(3, 6)
        for _ in range(n_trades):
            # jitter the timestamp within half a gap
            offset = random.uniform(-u['gap']/2, u['gap']/2)
            trade_time = ts + timedelta(minutes=offset)
            vol_amt    = round(random.uniform(10, 100), 2)
            sigs.append({
                'time': trade_time,
                'wallet': 'pred',
                'price': price,
                'volume_$': vol_amt,
                'balance_$': 0.0
            })
    df_sig = pd.DataFrame(sigs).sort_values('time')

    # 3) Resample into candles with OHLC + volume
    candles = resample_signals_to_candles(df_sig, interval)
    if candles.empty:
        await q.message.reply_text("Ошибка генерации свечей.", reply_markup=MAIN_MENU)
        return ConversationHandler.END

    # 4) Plot and send
    fig    = create_candlestick_figure(candles)
    html_b = fig_to_html_bytes(fig)
    pdf_b  = fig_to_pdf_bytes(fig)

    bio_html = BytesIO(html_b); bio_html.name = 'prediction.html'; bio_html.seek(0)
    bio_pdf  = BytesIO(pdf_b);  bio_pdf.name  = 'prediction.pdf';  bio_pdf.seek(0)

    await q.edit_message_text(f"Интервал {interval} выбран. Отправляю график…")
    await q.message.reply_document(document=bio_html, filename=bio_html.name)
    await q.message.reply_document(document=bio_pdf, filename=bio_pdf.name)
    await q.message.reply_text("Готово! Выберите команду:", reply_markup=MAIN_MENU)
    return ConversationHandler.END

# -------- CHART FLOW ----------
async def chart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Выберите интервал свечей для сигналов:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('5m', callback_data='5m'), InlineKeyboardButton('15m', callback_data='15m')],
            [InlineKeyboardButton('30m', callback_data='30m'), InlineKeyboardButton('4h', callback_data='4h')]
        ])
    )
    return CHOOSING_INTERVAL

async def chart_interval_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['interval'] = q.data
    await q.edit_message_text(f"Интервал {q.data} выбран.")
    await update.effective_chat.send_message(
        "Пришлите CSV или XLSX файл с сигналами.", reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_SIGNALS

async def chart_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        file = await update.message.document.get_file()
        suf = os.path.splitext(update.message.document.file_name)[1]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suf).name
        await file.download_to_drive(tmp)
        df = load_signals(tmp)
    else:
        df = parse_text_signals(update.message.text)
    candles = resample_signals_to_candles(df, context.user_data['interval'])
    if candles.empty:
        await update.message.reply_text("Нет данных для выбранного интервала.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    fig = create_candlestick_figure(candles)
    html_b = fig_to_html_bytes(fig)
    pdf_b  = fig_to_pdf_bytes(fig)
    bio_html = BytesIO(html_b); bio_html.name = 'chart.html'; bio_html.seek(0)
    bio_pdf  = BytesIO(pdf_b);  bio_pdf.name  = 'chart.pdf';  bio_pdf.seek(0)
    await update.message.reply_document(document=bio_html, filename=bio_html.name)
    await update.message.reply_document(document=bio_pdf,  filename=bio_pdf.name)
    await update.message.reply_text("Готово! Выберите команду:", reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.", reply_markup=MAIN_MENU)
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('predict', predict_cmd),
            CommandHandler('chart', chart_cmd)
        ],
        states={
            PRED_START_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_start_price)],
            PRED_POINTS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_points)],
            PRED_GAP:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_gap)],
            PRED_VOL:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_vol)],
            PRED_INTERVAL:    [CallbackQueryHandler(pred_interval_choice, pattern='^(5m|15m|30m|4h)$')],
            CHOOSING_INTERVAL:[CallbackQueryHandler(chart_interval_choice, pattern='^(5m|15m|30m|4h)$')],
            WAITING_SIGNALS:  [
                MessageHandler(filters.Document.ALL, chart_receive),
                MessageHandler(filters.TEXT & ~filters.COMMAND, chart_receive)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == '__main__':
    main()