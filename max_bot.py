"""
max_bot.py — Бот для MAX с автоматическими утренними рассылками
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
BOT_TOKEN = "f9LHodD0cOIE5o69a8MiMPDsXV_19u1hw66Zxpb7W5R081-N9m-7i-M1JKsXS7jdpFWYOWxnkGzE9x7by596"  # <-- ЗАМЕНИТЕ НА ВАШ ТОКЕН
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
logger.info("✅ Модель готова к работе")


# ============================================================================
# УПРАВЛЕНИЕ ПОДПИСЧИКАМИ
# ============================================================================
def load_subscribers():
    """Загрузка подписчиков из файла"""
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Поддержка старого формата (просто список user_id)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
                return {uid: uid for uid in data}  # Конвертируем в новый формат
            return data
    return {}


def save_subscribers(subscribers):
    """Сохранение подписчиков в файл"""
    with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(subscribers, f, ensure_ascii=False, indent=2)


# subscribers теперь словарь: {user_id: chat_id}
subscribers = load_subscribers()


def extract_chat_id(event):
    """Извлечение chat_id из события"""
    # Способ 1: get_ids() возвращает кортеж (chat_id, user_id)
    if hasattr(event, 'get_ids'):
        try:
            ids = event.get_ids()
            if isinstance(ids, tuple) and len(ids) >= 1:
                return str(ids[0])
        except Exception:
            pass

    # Способ 2: event.message.recipient.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient'):
        chat_id = getattr(event.message.recipient, 'chat_id', None)
        if chat_id:
            return str(chat_id)

    return ''


def extract_user_id(event):
    """Извлечение user_id из события"""
    if hasattr(event, 'get_ids'):
        try:
            ids = event.get_ids()
            if isinstance(ids, tuple) and len(ids) >= 2:
                return str(ids[1])
        except Exception:
            pass

    if hasattr(event, 'message') and hasattr(event.message, 'sender'):
        user_id = getattr(event.message.sender, 'user_id', None)
        if user_id:
            return str(user_id)

    return ''


# ============================================================================
# ФОНОВАЯ ЗАДАЧА: УТРЕННЯЯ РАССЫЛКА
# ============================================================================
async def morning_report_job():
    """Ежедневная рассылка в 10:00"""
    logger.info("🌅 Запуск утренней рассылки...")
    if not subscribers:
        logger.info("Нет подписчиков, рассылка пропущена.")
        return

    top_stocks = model.predict(n=5)
    response = "🌅 *Утренний обзор рынка от ИИ-Трейдера*\n\n"
    response += f" Дата: {datetime.now().strftime('%d.%m.%Y')}\n\n"
    for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
        response += f"{idx}. {format_stock_info(row)}\n\n"
    response += "⚠️ _Это не инвестиционная рекомендация._"

    successful_sends = 0
    for user_id, chat_id in subscribers.items():
        try:
            # Используем chat_id для отправки (MAX API требует chat_id)
            await bot.send_message(chat_id=int(chat_id), text=response)
            successful_sends += 1
            logger.info(f"✅ Отправлено пользователю {user_id} (chat_id: {chat_id})")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

    logger.info(f"✅ Утренняя рассылка завершена. Доставлено: {successful_sends}/{len(subscribers)}")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БОТА И ПЛАНИРОВЩИКА
# ============================================================================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

def extract_user_id(event):
    """Извлечение user_id"""
    if hasattr(event, 'get_ids'):
        try:
            ids = event.get_ids()
            if isinstance(ids, tuple) and len(ids) >= 2:
                return str(ids[1])
        except Exception:
            pass
    if hasattr(event, 'message') and hasattr(event.message, 'sender'):
        user_id = getattr(event.message.sender, 'user_id', None)
        if user_id:
            return str(user_id)
    return ''

def get_help_text():
    return (
        "👋 Привет! Я ИИ-Трейдер — помощник для анализа акций Московской биржи.\n\n"
        "📋 Команды:\n"
        "• /top — Топ-5 акций на сегодня\n"
        "• /top10 — Топ-10 акций\n"
        "• /ticker SBER — Анализ конкретной акции\n"
        "• /subscribe — Подписаться на утреннюю рассылку (10:00 МСК)\n"
        "• /unsubscribe — Отписаться от рассылки\n"
        "• /help — Эта справка\n\n"
        "💡 Быстрый анализ: просто напишите тикер (например, SBER, GAZP)"
    )

async def send_top_stocks(event, n=5):
    await event.message.answer("⏳ Анализирую рынок...")
    top_stocks = model.predict(n=n)
    response = f"🎯 *Топ-{n} акций на сегодня:*\n\n"
    for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
        response += f"{idx}. {format_stock_info(row)}\n\n"
    response += "⚠️ _Это не инвестиционная рекомендация._"
    await event.message.answer(response)

async def send_ticker_analysis(event, ticker_code):
    stock_data = model.get_ticker_info(ticker_code)
    if stock_data is not None:
        response = f"📊 *Анализ {ticker_code}:*\n\n{format_stock_info(stock_data)}"
        await event.message.answer(response)
    else:
        await event.message.answer(f"❌ Данные по {ticker_code} не найдены.")



# ============================================================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ============================================================================

@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    user_id = extract_user_id(event)
    if not user_id:
        logger.error("❌ Не удалось получить user_id в bot_started")
        return
    logger.info(f"🟢 Пользователь {user_id} запустил бота")
    await event.message.answer(get_help_text())


@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    user_id = extract_user_id(event)
    chat_id = extract_chat_id(event)

    if not user_id or not chat_id:
        logger.error("❌ Не удалось получить user_id или chat_id")
        return

    # 🔑 АВТОМАТИЧЕСКИ СОХРАНЯЕМ СВЯЗКУ user_id -> chat_id
    if user_id not in subscribers:
        subscribers[user_id] = chat_id
        save_subscribers(subscribers)
        logger.info(f"💾 Сохранен новый пользователь: user_id={user_id}, chat_id={chat_id}")
    else:
        # Обновляем chat_id если изменился
        subscribers[user_id] = chat_id
        save_subscribers(subscribers)

    msg = event.message
    body = getattr(msg, 'body', None)
    text = str(getattr(body, 'text', body)) if body else ''
    text = text.strip()

    if not text:
        return

    logger.info(f"📩 Сообщение от {user_id} (chat_id: {chat_id}): '{text}'")
    text_lower = text.lower()

    if text_lower in ['/start', '/help']:
        await msg.answer(get_help_text())

    elif text_lower == '/subscribe':
        await msg.answer(
            "✅ Вы успешно подписаны на утреннюю рассылку! Бот будет присылать Топ-5 акций каждый будний день в 10:00.")

    elif text_lower == '/unsubscribe':
        if user_id in subscribers:
            del subscribers[user_id]
            save_subscribers(subscribers)
            await msg.answer("❌ Вы отписаны от утренней рассылки.")
        else:
            await msg.answer("ℹ️ Вы и так не были подписаны на рассылку.")

    elif text_lower == '/top':
        await send_top_stocks(event, n=5)

    elif text_lower == '/top10':
        await send_top_stocks(event, n=10)

    elif text_lower.startswith('/ticker '):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            ticker_code = parts[1].strip().upper()
            if ticker_code in model.tickers:
                await send_ticker_analysis(event, ticker_code)
            else:
                await msg.answer(f"❌ Тикер {ticker_code} не найден. Доступные: {', '.join(model.tickers)}")

    else:
        ticker_code = text.upper()
        if ticker_code in model.tickers:
            await send_ticker_analysis(event, ticker_code)
        else:
            await msg.answer("❓ Напишите тикер акции (например, SBER) или команду /help")

# ============================================================================
# ЗАПУСК
# ============================================================================
async def main():
    logger.info("🤖 Запуск бота MAX с планировщиком...")

    try:
        await bot.delete_webhook()
        logger.info("✅ Webhook удален. Polling активирован.")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось удалить webhook: {e}")

    # 🕒 НАСТРОЙКА РАСПИСАНИЯ
    # По умолчанию: каждый день в 10:00 по московскому времени (timezone='Europe/Moscow')
    # Для тестирования прямо сейчас раскомментируйте строку ниже и закомментируйте cron:
    #scheduler.add_job(morning_report_job, 'interval', minutes=1)  # Тест: отправка через 1 минуту после запуска

    scheduler.add_job(morning_report_job, 'cron', hour=10, minute=0, timezone='Europe/Moscow')
    scheduler.start()
    logger.info("⏰ Планировщик запущен. Рассылка настроена на 10:00 МСК.")

    logger.info("💬 Откройте бота в MAX и нажмите 'Начать'")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
        scheduler.shutdown()