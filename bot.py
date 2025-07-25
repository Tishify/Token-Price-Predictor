import os
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    ContextTypes, filters
)

from price_models import random_walk
from signals import (
    load_signals, parse_text_signals,
    resample_signals_to_candles
)
from plot import (
    create_line_figure, create_candlestick_figure,
    fig_to_html_bytes, fig_to_pdf_bytes
)

# === STATES for /predict ===
PRED_START_PRICE, PRED_POINTS, PRED_GAP, PRED_VOL = range(4)
# === STATES for /chart ===
CHOOSING_INTERVAL, WAITING_SIGNALS = range(4, 6)

BOT_TOKEN = "8126937750:AAHhLOYTAexE0qQY3P55kcyBIUmx5JWC1ao" # set your token in env

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для предсказания цен и построения графиков по сигналам.\n"
        "Используй /predict для генерации цены или /chart для построения свечей по сигналам."
    )
    return ConversationHandler.END

# -------- PREDICT FLOW ----------
async def predict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Начальная цена?")
    return PRED_START_PRICE

async def pred_start_price(update, context):
    context.user_data["start_price"] = float(update.message.text)
    await update.message.reply_text("Сколько точек (например 50)?")
    return PRED_POINTS

async def pred_points(update, context):
    context.user_data["points"] = int(update.message.text)
    await update.message.reply_text("Интервал между точками в минутах (например 10)?")
    return PRED_GAP

async def pred_gap(update, context):
    context.user_data["gap"] = int(update.message.text)
    await update.message.reply_text("Волатильность в % (амплитуда шага, по умолчанию 2)?")
    return PRED_VOL

async def pred_vol(update, context):
    txt = update.message.text.strip()
    context.user_data["vol"] = float(txt) if txt else 2.0
    u = context.user_data
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=u["gap"] * (u["points"] - 1))
    df = random_walk(u["start_price"], start_time, end_time, u["points"], u["vol"])
    await send_curve(update, df, "prediction")
    return ConversationHandler.END

# -------- CHART FLOW ----------
async def chart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("5m", callback_data="5m"), InlineKeyboardButton("15m", callback_data="15m")],
        [InlineKeyboardButton("30m", callback_data="30m"), InlineKeyboardButton("4h", callback_data="4h")]
    ])
    await update.message.reply_text("Выберите интервал свечей:", reply_markup=kb)
    return CHOOSING_INTERVAL

async def chart_interval_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    interval = q.data
    context.user_data["interval"] = interval
    await q.edit_message_text(f"Интервал установлен: {interval}. Пришлите CSV или XLSX файл с сигналами.")
    return WAITING_SIGNALS

async def chart_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # загрузка сигналов
    if update.message.document:
        file = await update.message.document.get_file()
        tmp = tempfile.NamedTemporaryFile(delete=False).name
        await file.download_to_drive(tmp)
        df = load_signals(tmp)
    else:
        text = update.message.text
        df = parse_text_signals(text)

    candles = resample_signals_to_candles(df, context.user_data["interval"])
    if candles.empty:
        await update.message.reply_text("Нет данных для выбранного интервала.")
        return ConversationHandler.END

    fig = create_candlestick_figure(candles)
    html_b = fig_to_html_bytes(fig)
    pdf_b = fig_to_pdf_bytes(fig)

    bio_html = BytesIO(html_b); bio_html.name = "chart.html"; bio_html.seek(0)
    bio_pdf  = BytesIO(pdf_b);  bio_pdf.name  = "chart.pdf";  bio_pdf.seek(0)

    await update.message.reply_document(document=bio_html, filename=bio_html.name)
    await update.message.reply_document(document=bio_pdf,  filename=bio_pdf.name)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# -------- HELPERS ----------
async def send_curve(update_or_q, df, prefix: str):
    if df.empty:
        await update_or_q.message.reply_text("Нет данных для графика.")
        return
    # Выбираем тип графика по наличию колонок
    if 'open' in df.columns:
        fig = create_candlestick_figure(df)
    else:
        fig = create_line_figure(df)

    html_b = fig_to_html_bytes(fig)
    pdf_b = fig_to_pdf_bytes(fig)

    bio_html = BytesIO(html_b); bio_html.name = f"{prefix}.html"; bio_html.seek(0)
    bio_pdf  = BytesIO(pdf_b);  bio_pdf.name  = f"{prefix}.pdf";  bio_pdf.seek(0)

    await update_or_q.message.reply_document(document=bio_html, filename=bio_html.name)
    await update_or_q.message.reply_document(document=bio_pdf,  filename=bio_pdf.name)

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_predict = ConversationHandler(
        entry_points=[CommandHandler("predict", predict_cmd)],
        states={
            PRED_START_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_start_price)],
            PRED_POINTS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_points)],
            PRED_GAP:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_gap)],
            PRED_VOL:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_vol)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    conv_chart = ConversationHandler(
        entry_points=[CommandHandler("chart", chart_cmd)],
        states={
            CHOOSING_INTERVAL:   [CallbackQueryHandler(chart_interval_choice, pattern="^(5m|15m|30m|4h)$")],
            WAITING_SIGNALS:     [MessageHandler(filters.Document.ALL, chart_receive),
                                  MessageHandler(filters.TEXT & ~filters.COMMAND, chart_receive)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_predict)
    app.add_handler(conv_chart)
    app.run_polling()

if __name__ == "__main__":
    main()