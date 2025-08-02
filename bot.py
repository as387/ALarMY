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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "7c70d84340f4e9b9e99874cd465aefa8")
ADMIN_ID = 941791842
WEBHOOK_URL = 'https://din-js6l.onrender.com'

# --- Инициализация ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=utc)
moscow_tz = timezone('Europe/Moscow')

# --- Глобальные хранилища ---
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
            # Преобразуем ключи user_id обратно в строки, если они были сохранены как числа
            data = json.load(f)
            return {str(k): v for k, v in data.items()}
    except FileNotFoundError:
        logger.warning(f"Файл {filename} не найден. Будет использовано значение по умолчанию.")
        return default_value
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле {filename}. Будет использовано значение по умолчанию.")
        return default_value

# === 3. Клавиатуры ===

def get_main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("📋 Мои напоминания"),
        types.KeyboardButton("➕ Добавить напоминание"),
        types.KeyboardButton("🌤 Погода")
    )
    return keyboard

def get_weather_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🌦 Погода сейчас"))
    keyboard.add(types.KeyboardButton("⚙️ Настройки погоды"))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

def get_weather_settings_keyboard(user_id):
    settings = user_settings.get(str(user_id), {})
    notifications_on = settings.get('notifications_on', False)
    status_text = "❌ Выключить уведомления" if notifications_on else "✅ Включить уведомления"

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🏙 Изменить город"))
    keyboard.add(types.KeyboardButton("⏰ Изменить время"))
    keyboard.add(types.KeyboardButton(status_text))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню погоды"))
    return keyboard

def get_back_to_menu_keyboard(weather=False):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if weather:
        keyboard.add(types.KeyboardButton("↩️ Назад в меню погоды"))
    else:
        keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard
    
def create_reminder_inline_keyboard(reminder_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ Выполнено", callback_data=f"rem_done_{reminder_id}"),
        types.InlineKeyboardButton("🗑️ Удалить", callback_data=f"rem_delete_{reminder_id}")
    )
    return keyboard

# === 4. Вспомогательные функции ===

def ensure_user_data_exists(user_id):
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
    now = datetime.now(moscow_tz)
    full_match = re.match(r'^(\d{1,2})[.,](\d{1,2})\s+(\d{1,2})[.,:](\d{2})\s+(.+)', text.strip())
    if full_match:
        day, month, hour, minute, event = full_match.groups()
        dt_moscow = moscow_tz.localize(datetime(now.year, int(month), int(day), int(hour), int(minute)))
        return dt_moscow, event
    time_match = re.match(r'^(\d{1,2})[.,:](\d{2})\s+(.+)', text.strip())
    if time_match:
        hour, minute, event = time_match.groups()
        dt_moscow = moscow_tz.localize(datetime(now.year, now.month, now.day, int(hour), int(minute)))
        if dt_moscow < now:
            dt_moscow += timedelta(days=1)
        return dt_moscow, event
    return None, None

def parse_time_input(text):
    match = re.match(r'^(\d{1,2})[.,:](\d{2})$', text.strip())
    if match:
        hour, minute = map(int, match.groups())
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None

# === 5. Логика погоды ===

def get_and_format_24h_forecast(city):
    """Получает и форматирует прогноз на 24 часа."""
    url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Текущая погода
        current = data['list'][0]
        description = current['weather'][0]['description'].capitalize()
        temp = round(current['main']['temp'])
        
        weather_text = (
            f"📍 Погода в городе: *{city}*\n\n"
            f"Сейчас: *{description}*, температура *{temp}°C*\n\n"
            f"🗓️ *Прогноз на 24 часа:*\n"
        )
        
        # Прогноз на 8 периодов (24 часа)
        forecast_lines = []
        for forecast in data['list'][:8]:
            dt_moscow = datetime.fromtimestamp(forecast['dt']).astimezone(moscow_tz)
            time_str = dt_moscow.strftime('%H:%M')
            temp_str = f"{round(forecast['main']['temp'])}°C"
            desc_str = forecast['weather'][0]['description']
            forecast_lines.append(f"`{time_str}` - {temp_str}, {desc_str}")
        
        return weather_text + "\n".join(forecast_lines)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"❌ Город '{city}' не найден. Проверьте название в настройках."
        else:
            logger.error(f"HTTP ошибка при получении погоды для {city}: {e}")
            return "🌦️ Не удалось связаться с сервисом погоды. Попробуйте позже."
    except Exception as e:
        logger.error(f"Общая ошибка при получении погоды для {city}: {e}")
        return "🌦️ Произошла непредвиденная ошибка при получении прогноза."


# === 6. Обработчики команд и кнопок ===

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    ensure_user_data_exists(user_id)
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я твой бот-помощник. Умею ставить напоминания и показывать погоду.",
        reply_markup=get_main_menu_keyboard()
    )

# --- ИСПРАВЛЕННЫЙ БЛОК: ОТПРАВКА ИНСТРУКЦИИ ФАЙЛОМ ---
@bot.message_handler(commands=['help'])
def handle_help(message):
    """Отправляет пользователю инструкцию в виде .txt файла."""
    try:
        # Открываем файл в бинарном режиме ('rb') для отправки
        with open("instruction_extended.txt", "rb") as instruction_file:
            bot.send_document(
                message.chat.id,
                instruction_file,
                caption="📘 Вот полная инструкция по использованию бота."
            )
    except FileNotFoundError:
        logger.error("Файл инструкции 'instruction_extended.txt' не найден.")
        bot.send_message(message.chat.id, "К сожалению, файл с инструкцией сейчас недоступен. 😔")
    except Exception as e:
        # Эта ошибка может возникнуть, если у бота нет прав на отправку файлов и т.д.
        logger.error(f"Не удалось отправить файл инструкции: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при отправке файла с инструкцией.")
# --- КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ---

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню")
def handle_back_to_main_menu(message):
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu_keyboard())

# --- Блок Напоминаний ---
@bot.message_handler(func=lambda message: message.text in ["📋 Мои напоминания", "➕ Добавить напоминание"])
def handle_reminders_menu(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    if message.text == "📋 Мои напоминания":
        user_reminders = reminders.get(user_id, [])
        if not user_reminders:
            bot.send_message(message.chat.id, "У вас пока нет активных напоминаний.", reply_markup=get_main_menu_keyboard())
            return
        
        sorted_reminders = sorted(user_reminders, key=lambda x: x['time'])
        
        if not sorted_reminders:
            bot.send_message(message.chat.id, "У вас пока нет активных напоминаний.", reply_markup=get_main_menu_keyboard())
            return

        bot.send_message(message.chat.id, "Ваши активные напоминания:", reply_markup=get_main_menu_keyboard())
        for rem in sorted_reminders:
            dt_moscow = datetime.fromisoformat(rem['time']).astimezone(moscow_tz)
            text = f"🗓️ *{dt_moscow.strftime('%d.%m в %H:%M')}*\n_{rem['text']}_"
            bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=create_reminder_inline_keyboard(rem['id']))

    elif message.text == "➕ Добавить напоминание":
        msg = bot.send_message(message.chat.id, "Введите напоминание в формате:\n`ЧЧ:ММ событие`\nили\n`ДД.ММ ЧЧ:ММ событие`", parse_mode='Markdown', reply_markup=get_back_to_menu_keyboard())
        bot.register_next_step_handler(msg, process_new_reminder)


def process_new_reminder(message):
    if message.text == "↩️ Назад в меню": return handle_back_to_main_menu(message)
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    reminder_dt_moscow, event = parse_reminder_text(message.text)
    if not reminder_dt_moscow or not event:
        msg = bot.send_message(message.chat.id, "❌ Неверный формат. Попробуйте: `19:30 Ужин`", parse_mode='Markdown', reply_markup=get_back_to_menu_keyboard())
        bot.register_next_step_handler(msg, process_new_reminder)
        return
    reminder_dt_utc = reminder_dt_moscow.astimezone(utc)
    reminder_id = str(uuid.uuid4())
    new_reminder = {"id": reminder_id, "time": reminder_dt_utc.isoformat(), "text": event, "user_id": user_id}
    reminders[user_id].append(new_reminder)
    save_data(reminders, 'reminders.json')
    scheduler.add_job(send_reminder, trigger='date', run_date=reminder_dt_utc, args=[user_id, new_reminder], id=reminder_id)
    bot.send_message(message.chat.id, f"✅ Напоминание установлено на *{reminder_dt_moscow.strftime('%d.%m.%Y в %H:%M')}*", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('rem_'))
def handle_reminder_callback(call):
    user_id = str(call.from_user.id)
    action, reminder_id = call.data.split('_')[1:]
    found_rem = next((rem for rem in reminders.get(user_id, []) if rem['id'] == reminder_id), None)
    if not found_rem:
        bot.answer_callback_query(call.id, "Это напоминание уже неактивно.")
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="~~" + call.message.text + "~~", parse_mode='Markdown')
        return
    reminders[user_id].remove(found_rem)
    save_data(reminders, 'reminders.json')
    try: scheduler.remove_job(reminder_id)
    except Exception as e: logger.warning(f"Не удалось удалить задачу планировщика: {e}")
    message_text = f"✅ Выполнено: {found_rem['text']}" if action == 'done' else f"🗑️ Удалено: {found_rem['text']}"
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=message_text)
    bot.answer_callback_query(call.id, "Готово!")

# --- Блок Погоды ---

@bot.message_handler(func=lambda message: message.text == "🌤 Погода")
def handle_weather_menu(message):
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=get_weather_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню погоды")
def handle_back_to_weather_menu(message):
    handle_weather_menu(message)

@bot.message_handler(func=lambda message: message.text == "🌦 Погода сейчас")
def handle_today_weather(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    city = user_settings.get(user_id, {}).get('city', 'Москва')
    bot.send_chat_action(message.chat.id, 'typing')
    forecast_text = get_and_format_24h_forecast(city)
    bot.send_message(message.chat.id, forecast_text, parse_mode='Markdown')

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
    test_url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}"
    try:
        if requests.get(test_url, timeout=5).status_code != 200:
            bot.send_message(message.chat.id, f"❌ Город '{city}' не найден.", reply_markup=get_weather_menu_keyboard())
            return
    except requests.RequestException:
        bot.send_message(message.chat.id, "⚠️ Не удалось проверить город.", reply_markup=get_weather_menu_keyboard())
        return
    user_settings[user_id]['city'] = city
    save_data(user_settings, 'user_settings.json')
    bot.send_message(message.chat.id, f"✅ Город изменен на *{city}*.", parse_mode='Markdown', reply_markup=get_weather_menu_keyboard())
    # Обновляем задачу, если она была включена
    if user_settings[user_id].get('notifications_on', False):
        schedule_weather_job(user_id)

@bot.message_handler(func=lambda message: message.text == "⏰ Изменить время")
def handle_change_time(message):
    msg = bot.send_message(message.chat.id, "Введите новое время для ежедневных уведомлений в формате `ЧЧ:ММ` (например, `08:00` или `19.30`).", parse_mode='Markdown', reply_markup=get_back_to_menu_keyboard(weather=True))
    bot.register_next_step_handler(msg, process_time_input)

def process_time_input(message):
    if message.text == "↩️ Назад в меню погоды":
        return handle_weather_menu(message)
    user_id = str(message.from_user.id)
    new_time = parse_time_input(message.text)
    if not new_time:
        msg = bot.send_message(message.chat.id, "❌ Неверный формат. Пожалуйста, введите время как `ЧЧ:ММ`.", parse_mode='Markdown', reply_markup=get_back_to_menu_keyboard(weather=True))
        bot.register_next_step_handler(msg, process_time_input)
        return
    user_settings[user_id]['notification_time'] = new_time
    save_data(user_settings, 'user_settings.json')
    bot.send_message(message.chat.id, f"✅ Время уведомлений изменено на *{new_time}*.", parse_mode='Markdown')
    if user_settings[user_id].get('notifications_on', False):
        schedule_weather_job(user_id)
        bot.send_message(message.chat.id, "Расписание уведомлений обновлено.", reply_markup=get_weather_menu_keyboard())
    else:
        bot.send_message(message.chat.id, "Чтобы получать уведомления, не забудьте их включить.", reply_markup=get_weather_menu_keyboard())


@bot.message_handler(func=lambda message: message.text.endswith("уведомления"))
def handle_toggle_notifications(message):
    user_id = str(message.from_user.id)
    ensure_user_data_exists(user_id)
    
    current_status = user_settings[user_id].get('notifications_on', False)
    new_status = not current_status
    user_settings[user_id]['notifications_on'] = new_status
    save_data(user_settings, 'user_settings.json')

    if new_status:
        schedule_weather_job(user_id)
        bot.send_message(message.chat.id, "✅ Ежедневные уведомления о погоде включены.", reply_markup=get_weather_settings_keyboard(user_id))
    else:
        remove_weather_job(user_id)
        bot.send_message(message.chat.id, "❌ Ежедневные уведомления о погоде выключены.", reply_markup=get_weather_settings_keyboard(user_id))


# === 7. Планировщик и фоновые задачи ===

def send_reminder(user_id, reminder_data):
    logger.info(f"Отправка напоминания {reminder_data['id']} пользователю {user_id}")
    try:
        text = f"🔔 *Напоминание!*\n\n_{reminder_data['text']}_"
        bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=create_reminder_inline_keyboard(reminder_data['id']))
    except Exception as e:
        logger.error(f"Не удалось отправить напоминание {reminder_data['id']}: {e}")

def send_daily_weather_forecast(user_id):
    logger.info(f"Отправка ежедневного прогноза погоды пользователю {user_id}")
    user_id_str = str(user_id)
    city = user_settings.get(user_id_str, {}).get('city', 'Москва')
    forecast_text = get_and_format_24h_forecast(city)
    try:
        bot.send_message(user_id, forecast_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Не удалось отправить прогноз погоды {user_id_str}: {e}")
        
def schedule_weather_job(user_id):
    user_id_str = str(user_id)
    job_id = f"weather_{user_id_str}"
    settings = user_settings.get(user_id_str, {})
    time_str = settings.get('notification_time', '07:30')
    hour, minute = map(int, time_str.split(':'))
    
    scheduler.add_job(
        send_daily_weather_forecast,
        trigger='cron',
        hour=hour,
        minute=minute,
        timezone=moscow_tz, # Уведомления приходят по московскому времени
        args=[user_id],
        id=job_id,
        replace_existing=True
    )
    logger.info(f"Задача '{job_id}' запланирована на {time_str} (MSK).")

def remove_weather_job(user_id):
    job_id = f"weather_{user_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Задача '{job_id}' удалена.")
    except Exception:
        logger.warning(f"Не удалось удалить задачу '{job_id}' (возможно, ее не существует).")

def restore_jobs():
    logger.info("Восстановление задач...")
    # Восстановление напоминаний
    reminders.clear(); reminders.update(load_data('reminders.json', {}))
    rem_restored = 0
    for user_id, user_reminders in reminders.items():
        for rem in user_reminders:
            if datetime.fromisoformat(rem['time']) > datetime.now(utc):
                scheduler.add_job(send_reminder, trigger='date', run_date=rem['time'], args=[rem['user_id'], rem], id=rem['id'], replace_existing=True)
                rem_restored += 1
    logger.info(f"Восстановлено {rem_restored} напоминаний.")

    # Восстановление уведомлений о погоде
    user_settings.clear(); user_settings.update(load_data('user_settings.json', {}))
    weather_restored = 0
    for user_id, settings in user_settings.items():
        if settings.get('notifications_on', False):
            schedule_weather_job(user_id)
            weather_restored += 1
    logger.info(f"Восстановлено {weather_restored} задач на уведомления о погоде.")


# === 8. Webhook и запуск ===

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    return "Invalid request", 400

@app.route("/", methods=["GET"])
def root(): return "Bot is running..."

def self_ping():
    while True:
        try:
            requests.head(WEBHOOK_URL, timeout=10)
            logger.info(f"[PING] Self-ping successful.")
        except Exception as e:
            logger.error(f"[PING ERROR] {e}")
        sleep(300)

if __name__ == "__main__":
    logger.info("Запуск бота...")
    scheduler.start()
    restore_jobs()
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/' + BOT_TOKEN)
    logger.info(f"Вебхук установлен: {WEBHOOK_URL}")
    ping_thread = threading.Thread(target=self_ping); ping_thread.daemon = True; ping_thread.start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
