"""
max_bot.py — Финальная рабочая версия (без клавиатур, только текстовые команды)
"""

import asyncio
import logging
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, MessageCreated
from model import StockModel, get_verdict, format_stock_info

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
BOT_TOKEN = "f9LHodD0cOIE5o69a8MiMPDsXV_19u1hw66Zxpb7W5R081-N9m-7i-M1JKsXS7jdpFWYOWxnkGzE9x7by596"  # <-- ЗАМЕНИТЕ
SUBSCRIBERS_FILE = "subscribers.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# ЗАГРУЗКА МОДЕЛИ
# ============================================================================
logger.info("🔄 Загрузка модели...")
model = StockModel()
model.load_data()
model.add_features()
model.train()
logger.info(f"✅ Модель готова. Анализируем {len(model.tickers)} акций")

# ============================================================================
# ПОДПИСЧИКИ
# ============================================================================
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return {uid: uid for uid in data}
            return data
    return {}

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

subscribers = load_subscribers()

# ============================================================================
# ИЗВЛЕЧЕНИЕ ID
# ============================================================================
def extract_user_id(event):
    try:
        ids = event.get_ids()
        if isinstance(ids, tuple) and len(ids) >= 2:
            return str(ids[1])
    except Exception:
        pass
    return ''

def extract_chat_id(event):
    try:
        ids = event.get_ids()
        if isinstance(ids, tuple) and len(ids) >= 1:
            return str(ids[0])
    except Exception:
        pass
    return ''

# ============================================================================
# ФУНКЦИИ ОТВЕТОВ
# ============================================================================
def get_help_text():
    return (
        "👋 Привет! Я ИИ-Трейдер — помощник для анализа акций Московской биржи.\n\n"
        "📋 Команды:\n"
        "• /top — Топ-5 акций на сегодня\n"
        "• /top10 — Топ-10 акций\n"
        "• /ticker SBER — Анализ конкретной акции\n"
        "• /subscribe — Подписаться на утреннюю рассылку (10:00 МСК)\n"
        "• /unsubscribe — Отписаться\n"
        "• /help — Эта справка\n\n"
        "💡 Быстрый анализ: просто напишите тикер (например, SBER, GAZP, LKOH)"
        "ссылка на песочницу "
    )

async def send_top_stocks(msg, n=5):
    await msg.answer("⏳ Анализирую рынок...")
    top_stocks = model.predict(n=n)
    response = f"🎯 *Топ-{n} акций на сегодня:*\n\n"
    for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
        response += f"{idx}. {format_stock_info(row)}\n\n"
    response += "⚠️ _Это не инвестиционная рекомендация._"
    await msg.answer(response)

async def send_ticker_analysis(msg, ticker_code):
    stock_data = model.get_ticker_info(ticker_code)
    if stock_data is not None:
        response = f"📊 *Анализ {ticker_code}:*\n\n{format_stock_info(stock_data)}"
        await msg.answer(response)
    else:
        await msg.answer(f"❌ Данные по {ticker_code} не найдены.")

# ============================================================================
# УТРЕННЯЯ РАССЫЛКА
# ============================================================================
async def morning_report_job():
    logger.info("🌅 Запуск утренней рассылки...")
    if not subscribers:
        logger.info("Нет подписчиков.")
        return

    top_stocks = model.predict(n=5)
    response = "🌅 *Утренний обзор рынка*\n\n"
    response += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
        response += f"{idx}. {format_stock_info(row)}\n\n"
    response += "⚠️ _Не инвестиционная рекомендация._"

    sent = 0
    for user_id, chat_id in subscribers.items():
        try:
            # Для рассылки используем встроенный метод бота
            await bot.send_message(chat_id=int(chat_id), text=response)
            sent += 1
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {user_id}: {e}")

    logger.info(f"✅ Рассылка завершена: {sent}/{len(subscribers)}")

# ============================================================================
# ОБРАБОТЧИКИ
# ============================================================================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    user_id = extract_user_id(event)
    chat_id = extract_chat_id(event)

    if not user_id:
        logger.error("❌ Не удалось получить user_id")
        return

    logger.info(f"🟢 Пользователь {user_id} запустил бота")

    if user_id and chat_id:
        subscribers[user_id] = chat_id
        save_subscribers(subscribers)

    # ✅ РАБОЧИЙ МЕТОД: встроенный answer()
    await event.message.answer(get_help_text())

@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    user_id = extract_user_id(event)
    chat_id = extract_chat_id(event)

    if not user_id:
        return

    if user_id and chat_id:
        subscribers[user_id] = chat_id
        save_subscribers(subscribers)

    msg = event.message
    body = getattr(msg, 'body', None)
    text = str(getattr(body, 'text', body)) if body else ''
    text = text.strip()

    if not text:
        return

    logger.info(f"📩 Сообщение от {user_id}: '{text}'")
    text_lower = text.lower()

    if text_lower in ['/start', '/help']:
        await msg.answer(get_help_text())

    elif text_lower == '/subscribe':
        await msg.answer("✅ Вы подписаны на утреннюю рассылку (10:00 МСК)!")

    elif text_lower == '/unsubscribe':
        if user_id in subscribers:
            del subscribers[user_id]
            save_subscribers(subscribers)
            await msg.answer("❌ Вы отписаны от рассылки.")
        else:
            await msg.answer("ℹ️ Вы и так не были подписаны.")

    elif text_lower == '/top':
        await send_top_stocks(msg, n=5)

    elif text_lower == '/top10':
        await send_top_stocks(msg, n=10)

    elif text_lower.startswith('/ticker '):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            ticker_code = parts[1].strip().upper()
            if ticker_code in model.tickers:
                await send_ticker_analysis(msg, ticker_code)
            else:
                await msg.answer(f"❌ Тикер не найден. Доступные: {', '.join(model.tickers[:10])}...")

    else:
        ticker_code = text.upper()
        if ticker_code in model.tickers:
            await send_ticker_analysis(msg, ticker_code)
        else:
            await msg.answer("❓ Напишите тикер (например, SBER) или /help")

# ============================================================================
# ЗАПУСК
# ============================================================================
async def main():
    logger.info("🤖 Запуск бота MAX...")

    try:
        await bot.delete_webhook()
        logger.info("✅ Webhook удален")
    except Exception as e:
        logger.warning(f"⚠️ {e}")

    scheduler.add_job(morning_report_job, 'cron', hour=10, minute=0, timezone='Europe/Moscow')
    scheduler.start()
    logger.info("⏰ Рассылка настроена на 10:00 МСК")

    logger.info("💬 Откройте бота в MAX")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
        scheduler.shutdown()