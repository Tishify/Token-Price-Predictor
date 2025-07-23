import os
import tempfile
from datetime import datetime, timedelta
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          ConversationHandler, CallbackQueryHandler,
                          ContextTypes, filters)

from price_models import random_walk
from signals import parse_text_signals, parse_file_signals, build_curve_from_signals
from io import BytesIO
from plot import fig_to_html_bytes, fig_to_pdf_bytes, price_plot

# === STATES ===
PRED_START_PRICE, PRED_POINTS, PRED_GAP, PRED_VOL = range(4)
SIG_WAITING_INPUT, SIG_WAITING_FILE_OR_TEXT = range(4,6)

BOT_TOKEN = "8126937750:AAHhLOYTAexE0qQY3P55kcyBIUmx5JWC1ao"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот для предсказания цен и построения графиков по сигналам.")
    await update.message.reply_text("Используй команды /predict для предсказания цен и /signals для построения графиков по сигналам.")
    
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
    end_time = start_time + timedelta(minutes=u["gap"]*(u["points"]-1))
    df = random_walk(u["start_price"], start_time, end_time, u["points"], u["vol"])

    await send_curve(update, df, "prediction")
    return ConversationHandler.END

# -------- SIGNALS FLOW ----------
async def signals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Текстом", callback_data="sig_text"),
        InlineKeyboardButton("🗂 Файл (csv/xlsx)", callback_data="sig_file")
    ]])
    await update.message.reply_text("Как дашь сигналы?", reply_markup=kb)
    return SIG_WAITING_INPUT

async def signals_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "sig_text":
        await q.edit_message_text("Кидай текст. Формат строк:\n`YYYY-MM-DD HH:MM buy|sell pct price(optional)`")
        return SIG_WAITING_FILE_OR_TEXT
    else:
        await q.edit_message_text("Ок, пришли csv или xlsx файлом.")
        return SIG_WAITING_FILE_OR_TEXT

async def signals_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        # file
        file = await update.message.document.get_file()
        tmp = tempfile.NamedTemporaryFile(delete=False).name
        await file.download_to_drive(tmp)
        df_sig = parse_file_signals(tmp)
    else:
        # text
        text = update.message.text
        df_sig = parse_text_signals(text)

    curve = build_curve_from_signals(df_sig, start_price=df_sig.get("price").dropna().iloc[0] if "price" in df_sig else 0.01)

    print(df_sig.head(), df_sig.shape)
    await update.message.reply_text(f"DEBUG: {df_sig.shape[0]} точек, первые цены: {df_sig['price'].head().tolist()}")

    await send_curve(update, curve, "signals")
    return ConversationHandler.END


# -------- HELPERS ----------
async def send_curve(update_or_q, df, prefix: str):
    if df.empty:
        await update_or_q.message.reply_text("no info to plot.")
        return
    fig = price_plot(df)

    html_b = fig_to_html_bytes(fig)
    bio_html = BytesIO(html_b); bio_html.name = f"{prefix}.html"; bio_html.seek(0)

    # PDF
    pdf_b = fig_to_pdf_bytes(fig)
    bio_pdf = BytesIO(pdf_b);  bio_pdf.name  = f"{prefix}.pdf";  bio_pdf.seek(0)

    await update_or_q.message.reply_document(document=bio_html, filename=bio_html.name)
    await update_or_q.message.reply_document(document=bio_pdf,  filename=bio_pdf.name)
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /predict conversation
    conv_predict = ConversationHandler(
        entry_points=[CommandHandler("predict", predict_cmd)],
        states={
            PRED_START_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_start_price)],
            PRED_POINTS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_points)],
            PRED_GAP:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_gap)],
            PRED_VOL:         [MessageHandler(filters.TEXT & ~filters.COMMAND, pred_vol)],
        },
        fallbacks=[]
    )

    # /signals conversation
    conv_signals = ConversationHandler(
        entry_points=[CommandHandler("signals", signals_cmd)],
        states={
            SIG_WAITING_INPUT: [CallbackQueryHandler(signals_choice, pattern="^sig_")],
            SIG_WAITING_FILE_OR_TEXT: [
                MessageHandler(filters.Document.ALL, signals_receive),
                MessageHandler(filters.TEXT & ~filters.COMMAND, signals_receive)
            ]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_predict)
    app.add_handler(conv_signals)
    app.run_polling()

if __name__ == "__main__":
    main()
