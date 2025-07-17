# -*- coding: utf-8 -*-

# === 1. Импорты и базовые настройки ===
import os
import logging
import json
import re
import uuid
import threading
from time import sleep
from datetime import datetime, timedelta

import requests
from flask import Flask, request
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone, utc

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Константы и конфигурация ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")  # Рекомендуется хранить токен в переменных окружения
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "7c70d84340f4e9b9e99874cd465aefa8") # Рекомендуется хранить ключ в переменных окружения
ADMIN_ID = 941791842  # Ваш Telegram ID
WEBHOOK_URL = 'https://din-js6l.onrender.com' # URL для вебхука

# --- Инициализация ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=utc)
moscow_tz = timezone('Europe/Moscow')

# --- Глобальные хранилища (в реальном приложении лучше использовать базу данных) ---
reminders = {}
user_settings = {}  # { "user_id": {"city": "Москва", "notification_time": "07:30", "notifications_on": False}}

# === 2. Управление данными (сохранение и загрузка) ===

def save_data(data, filename):
    """Универсальная функция для сохранения данных в JSON."""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4, default=str)
    except Exception as e:
        logger.error(f"Ошибка при сохранении файла {filename}: {e}")

def load_data(filename, default_value):
    """Универсальная функция для загрузки данных из JSON."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Файл {filename} не найден. Будет использовано значение по умолчанию.")
        return default_value
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле {filename}. Будет использовано значение по умолчанию.")
        return default_value

# === 3. Клавиатуры ===

def get_main_menu_keyboard():
    """Возвращает клавиатуру главного меню."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("📋 Мои напоминания"),
        types.KeyboardButton("➕ Добавить напоминание"),
        types.KeyboardButton("🌤 Погода")
    )
    return keyboard

def get_reminders_keyboard():
    """Возвращает клавиатуру для управления напоминаниями."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("➕ Добавить напоминание"))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard
    
def get_weather_menu_keyboard():
    """Возвращает клавиатуру меню погоды."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🌦 Погода сегодня"))
    keyboard.add(types.KeyboardButton("⚙️ Настройки погоды"))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

def get_weather_settings_keyboard(user_id):
    """Возвращает клавиатуру настроек погоды."""
    settings = user_settings.get(str(user_id), {})
    notifications_on = settings.get('notifications_on', False)
    status_text = "✅ Включить уведомления" if not notifications_on else "❌ Выключить уведомления"

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🏙 Изменить город"))
    keyboard.add(types.KeyboardButton("⏰ Изменить время"))
    keyboard.add(types.KeyboardButton(status_text))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню погоды"))
    return keyboard

def get_back_to_menu_keyboard():
    """Возвращает клавиатуру с кнопкой "Назад в меню"."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

def create_reminder_inline_keyboard(reminder_id):
    """Создает inline-клавиатуру для одного напоминания."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ Выполнено", callback_data=f"rem_done_{reminder_id}"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"rem_delete_{reminder_id}")
    )
    return keyboard

# === 4. Вспомогательные функции ===

def ensure_user_data_exists(user_id):
    """Проверяет и создает записи для нового пользователя."""
    user_id_str = str(user_id)
    if user_id_str not in reminders:
        reminders[user_id_str] = []
    if user_id_str not in user_settings:
        user_settings[user_id_str] = {
            "city": "Москва",
            "notification_time": "07:30",
            "notifications_on": False
        }

def parse_reminder_text(text):
    """Парсит текст напоминания и возвращает время и событие."""
    now = datetime.now(moscow_tz)
    
    # Формат: ДД.ММ ЧЧ.ММ событие
    full_match = re.match(r'^(\d{1,2})[.,](\d{1,2})\s+(\d{1,2})[.,:](\d{2})\s+(.+)', text.strip())
    if full_match:
        day, month, hour, minute, event = full_match.groups()
        dt_moscow = moscow_tz.localize(datetime(now.year, int(month), int(day), int(hour), int(minute)))
        return dt_moscow, event

    # Формат: ЧЧ.ММ событие
    time_match = re.match(r'^(\d{1,2})[.,:](\d{2})\s+(.+)', text.strip())
    if time_match:
        hour, minute, event = time_match.groups()
        dt_moscow = moscow_tz.localize(datetime(now.year, now.month, now.day, int(hour), int(minute)))
        if dt_moscow < now: # если время сегодня уже прошло, ставим на завтра
            dt_moscow += timedelta(days=1)
        return dt_moscow, event

    return None, None
    
# === 5. Обработчики команд и кнопок ===

@bot.message_handler(commands=['start'])
def handle_start(message):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    ensure_user_data_exists(user_id)
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я твой бот-помощник. Умею ставить напоминания и показывать погоду.",
        reply_markup=get_main_menu_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню")
def handle_back_to_main_menu(message):
    """Обработчик кнопки 'Назад в меню'."""
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu_keyboard())

# --- Блок Напоминаний ---

@bot.message_handler(func=lambda message: message.text in ["📋 Мои напоминания", "➕ Добавить напоминание"])
def handle_reminders_menu(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    
    if message.text == "📋 Мои напоминания":
        user_reminders = reminders.get(user_id, [])
        if not user_reminders:
            bot.send_message(
                message.chat.id,
                "У вас пока нет активных напоминаний. Давайте добавим первое?",
                reply_markup=get_reminders_keyboard()
            )
            return

        bot.send_message(message.chat.id, "Ваши активные напоминания:", reply_markup=get_reminders_keyboard())
        sorted_reminders = sorted(user_reminders, key=lambda x: x['time'])
        for rem in sorted_reminders:
            dt_moscow = datetime.fromisoformat(rem['time']).astimezone(moscow_tz)
            text = f"🗓️ *{dt_moscow.strftime('%d.%m в %H:%M')}*\n_{rem['text']}_"
            bot.send_message(
                message.chat.id,
                text,
                parse_mode='Markdown',
                reply_markup=create_reminder_inline_keyboard(rem['id'])
            )
    
    elif message.text == "➕ Добавить напоминание":
        msg = bot.send_message(
            message.chat.id,
            "Введите напоминание в формате:\n`ЧЧ:ММ событие`\nили\n`ДД.ММ ЧЧ:ММ событие`",
            parse_mode='Markdown',
            reply_markup=get_back_to_menu_keyboard()
        )
        bot.register_next_step_handler(msg, process_new_reminder)

def process_new_reminder(message):
    """Обрабатывает введенное пользователем напоминание."""
    if message.text == "↩️ Назад в меню":
        return handle_back_to_main_menu(message)
        
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    
    reminder_dt_moscow, event = parse_reminder_text(message.text)
    
    if not reminder_dt_moscow or not event:
        msg = bot.send_message(
            message.chat.id,
            "❌ Неверный формат. Пожалуйста, попробуйте еще раз. Например: `19:30 Сходить в магазин`",
            parse_mode='Markdown',
            reply_markup=get_back_to_menu_keyboard()
        )
        bot.register_next_step_handler(msg, process_new_reminder)
        return

    reminder_dt_utc = reminder_dt_moscow.astimezone(utc)
    
    reminder_id = str(uuid.uuid4())
    new_reminder = {
        "id": reminder_id,
        "time": reminder_dt_utc.isoformat(),
        "text": event,
        "user_id": user_id
    }
    
    reminders[user_id].append(new_reminder)
    save_data(reminders, 'reminders.json')
    
    scheduler.add_job(
        send_reminder,
        trigger='date',
        run_date=reminder_dt_utc,
        args=[user_id, new_reminder],
        id=reminder_id
    )
    
    bot.send_message(
        message.chat.id,
        f"✅ Напоминание установлено на *{reminder_dt_moscow.strftime('%d.%m.%Y в %H:%M')}*",
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('rem_'))
def handle_reminder_callback(call):
    """Обрабатывает нажатия на inline-кнопки под напоминаниями."""
    user_id = str(call.from_user.id)
    action, reminder_id = call.data.split('_')[1:]

    # Находим напоминание и удаляем его из списка и планировщика
    found_rem = None
    for rem in reminders.get(user_id, []):
        if rem['id'] == reminder_id:
            found_rem = rem
            break
            
    if not found_rem:
        bot.answer_callback_query(call.id, "Это напоминание уже неактивно.")
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="~~" + call.message.text + "~~", parse_mode='Markdown')
        return

    reminders[user_id].remove(found_rem)
    save_data(reminders, 'reminders.json')
    
    try:
        scheduler.remove_job(reminder_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить задачу из планировщика (возможно, она уже выполнена): {e}")

    if action == 'done':
        message_text = f"✅ Выполнено: {found_rem['text']}"
    else: # delete
        message_text = f"🗑️ Удалено: {found_rem['text']}"
        
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=message_text
    )
    bot.answer_callback_query(call.id, "Готово!")

# --- Блок Погоды ---

@bot.message_handler(func=lambda message: message.text == "🌤 Погода")
def handle_weather_menu(message):
    """Показывает меню погоды."""
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=get_weather_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню погоды")
def handle_back_to_weather_menu(message):
    """Возвращает в меню погоды."""
    handle_weather_menu(message)
    
@bot.message_handler(func=lambda message: message.text == "🌦 Погода сегодня")
def handle_today_weather(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    city = user_settings.get(user_id, {}).get('city', 'Москва')
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        description = data['weather'][0]['description'].capitalize()
        temp = round(data['main']['temp'])
        feels_like = round(data['main']['feels_like'])
        wind = data['wind']['speed']
        
        weather_text = (
            f"📍 Погода в городе: *{city}*\n\n"
            f"{description}\n"
            f"🌡️ Температура: *{temp}°C*\n"
            f"🖐️ Ощущается как: *{feels_like}°C*\n"
            f"💨 Ветер: {wind} м/с"
        )
        bot.send_message(message.chat.id, weather_text, parse_mode='Markdown')
        
    except requests.exceptions.RequestException:
        bot.send_message(message.chat.id, "🌦️ Не удалось связаться с сервисом погоды. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка получения погоды для {city}: {e}")
        bot.send_message(message.chat.id, "🌦️ Произошла ошибка при получении прогноза. Возможно, неверно указан город.")

@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки погоды")
def handle_weather_settings(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    settings = user_settings[user_id]
    
    text = (
        f"⚙️ *Настройки погоды*\n\n"
        f"Город: *{settings.get('city', 'Не задан')}*\n"
        f"Время уведомлений: *{settings.get('notification_time', '07:30')}*\n"
        f"Статус уведомлений: *{'Включены' if settings.get('notifications_on') else 'Выключены'}*"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=get_weather_settings_keyboard(user_id))

@bot.message_handler(func=lambda message: message.text == "🏙 Изменить город")
def handle_change_city(message):
    msg = bot.send_message(message.chat.id, "Введите название города:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_city_input)

def process_city_input(message):
    user_id = str(message.from_user.id)
    city = message.text.strip()
    
    # Проверяем, существует ли город
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            bot.send_message(message.chat.id, f"❌ Город '{city}' не найден. Попробуйте еще раз.", reply_markup=get_weather_menu_keyboard())
            return
    except requests.exceptions.RequestException:
        bot.send_message(message.chat.id, "⚠️ Не удалось проверить город. Попробуйте позже.", reply_markup=get_weather_menu_keyboard())
        return

    user_settings[user_id]['city'] = city
    save_data(user_settings, 'user_settings.json')
    bot.send_message(message.chat.id, f"✅ Город изменен на *{city}*.", parse_mode='Markdown', reply_markup=get_weather_menu_keyboard())


# === 6. Планировщик и фоновые задачи ===

def send_reminder(user_id, reminder_data):
    """Отправляет сообщение с напоминанием."""
    logger.info(f"Отправка напоминания {reminder_data['id']} пользователю {user_id}")
    try:
        text = f"🔔 *Напоминание!*\n\n_{reminder_data['text']}_"
        bot.send_message(
            user_id,
            text,
            parse_mode='Markdown',
            reply_markup=create_reminder_inline_keyboard(reminder_data['id'])
        )
    except Exception as e:
        logger.error(f"Не удалось отправить напоминание {reminder_data['id']}: {e}")

def restore_jobs():
    """Восстанавливает задачи планировщика после перезапуска."""
    logger.info("Восстановление задач из файла reminders.json...")
    loaded_reminders = load_data('reminders.json', {})
    reminders.update(loaded_reminders) # Обновляем глобальную переменную
    
    jobs_restored = 0
    for user_id, user_reminders in reminders.items():
        for rem in user_reminders:
            reminder_dt_utc = datetime.fromisoformat(rem['time']).astimezone(utc)
            if reminder_dt_utc > datetime.now(utc):
                scheduler.add_job(
                    send_reminder,
                    trigger='date',
                    run_date=reminder_dt_utc,
                    args=[user_id, rem],
                    id=rem['id'],
                    replace_existing=True
                )
                jobs_restored += 1
    logger.info(f"Восстановлено {jobs_restored} задач.")


# === 7. Webhook и запуск ===

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    return "Invalid request", 400

@app.route("/", methods=["GET"])
def root():
    return "Bot is running...", 200

def self_ping():
    """Поддерживает активность бота на бесплатных хостингах."""
    while True:
        try:
            requests.head(WEBHOOK_URL, timeout=10)
            logger.info(f"[PING] Self-ping successful.")
        except Exception as e:
            logger.error(f"[PING ERROR] {e}")
        sleep(300) # пингуем каждые 5 минут

if __name__ == "__main__":
    logger.info("Запуск бота...")
    
    # Загружаем данные
    reminders.update(load_data('reminders.json', {}))
    user_settings.update(load_data('user_settings.json', {}))

    # Запускаем планировщик и восстанавливаем задачи
    scheduler.start()
    restore_jobs()
    
    # Настраиваем вебхук
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/' + BOT_TOKEN)
    logger.info(f"Вебхук установлен: {WEBHOOK_URL}")

    # Запускаем self-ping в отдельном потоке
    ping_thread = threading.Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()

    # Запускаем Flask-приложение
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
