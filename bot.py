# === ОГЛАВЛЕНИЕ ===
# 1. Импорты и настройки — строка 13
# 2. Блок общих команд — строка 239
# 3. Блок обработчиков текста — строка ?
# 4. Блок функций для напоминаний — строка 342
# 5. Блок служебных функций — строка 191
# 6. Блок Webhook и self-ping — строка 701
# 7. Главный блок запуска — строка 822

# 7. Главный блок запуска

import requests
import time
from flask import Flask, request
from bs4 import BeautifulSoup
import telebot
# === 1. Импорты и настройки ===
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import uuid
import re
from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from functools import lru_cache
import requests
from datetime import datetime

import json

# Глобальная переменная для хранения настроек погоды
user_weather_settings = {}

def save_weather_settings():
    try:
        with open('weather_settings.json', 'w') as f:
            json.dump(user_weather_settings, f)
    except Exception as e:
        logger.error(f"Error saving weather settings: {e}")

def load_weather_settings():
    global user_weather_settings
    try:
        with open('weather_settings.json', 'r') as f:
            user_weather_settings = json.load(f)
    except FileNotFoundError:
        user_weather_settings = {}

def back_to_weather_settings_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("↩️ Назад в меню погоды"))
    return keyboard

# Кэшируем запросы на 10 минут (600 секунд)
@lru_cache(maxsize=10)
def get_cached_weather(api_key: str, city: str):
    """Получает и кэширует данные о погоде"""
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=ru"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка при запросе погоды: {str(e)}")
        return None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Weather:
    def __init__(self, period, temperature, feels_like, weather_desc, wind_speed, wind_dir, humidity, pressure):
        self.period = period
        self.temperature = temperature
        self.feels_like = feels_like
        self.weather_desc = weather_desc
        self.wind_speed = wind_speed
        self.wind_dir = wind_dir
        self.humidity = humidity
        self.pressure = pressure

        # Флаги для вывода
        self.period_flag = True
        self.temperature_flag = True
        self.feels_like_flag = True
        self.weather_desc_flag = True
        self.wind_speed_flag = False
        self.wind_dir_flag = False
        self.humidity_flag = False
        self.pressure_flag = False

    @staticmethod
    def from_openweather_data(time_str, data):
        # Определяем направление ветра по градусам
        wind_deg = data.get('wind_deg', 0)
        directions = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ']
        wind_dir = directions[round(wind_deg / 45) % 8] if 'wind_deg' in data else ""
        
        return Weather(
            period=time_str,
            temperature=f"{round(data['temp'])}°",
            feels_like=f"{round(data['feels_like'])}°",
            weather_desc=data['description'],
            wind_speed=f"{data['wind_speed']} м/с",
            wind_dir=wind_dir,
            humidity=f"{data['humidity']}%",
            pressure=f"{data['pressure']} гПа"
        )

def get_weather_settings_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("🏙 Изменить город")
    keyboard.row("↩️ Назад в меню погоды")
    return keyboard
    
def get_weather_forecast(api_key: str, city: str = "Москва") -> dict:
    """Получает прогноз погоды с обработкой всех ошибок"""
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=ru"
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Проверяем структуру ответа
        if not isinstance(data.get('list'), list):
            raise ValueError("Некорректный формат данных от API")
            
        return data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Ошибка обработки данных: {str(e)}")
        return None

def parse_yandex_forecast(raw_text):
    pattern = re.compile(
        r"(Утром|Днём|Вечером|Ночью)\+(\d+)[°º]([а-яА-Я\s]+?)\+(\d+)[°º](\d+)\s?м/с([А-Яа-я]+)(\d+)%(\d+)"
    )

    matches = pattern.findall(raw_text)
    forecast_data = []

    for part in matches:
        period, temp, desc, feels_like, wind_speed, wind_dir, humidity, pressure = part
        
        weather = Weather(
            period=period,
            temperature=f"{temp}°",
            feels_like=f"{feels_like}°",
            weather_desc=desc.strip(),
            wind_speed=f"{wind_speed} м/с",
            wind_dir=wind_dir,
            humidity=f"{humidity}%",
            pressure=f"{pressure} мм рт. ст."
        )

        # Можно гибко управлять флагами
        # Например, если не нужно показывать "ощущается как":
        weather.set_flag('feels_like_flag', False)

        forecast_data.append(weather)

    return forecast_data

menu_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
menu_keyboard.add(
    KeyboardButton("🆕 Добавить"),
    KeyboardButton("🔁 Повтор")
)
menu_keyboard.add(
    KeyboardButton("🌤 Погода")
)
menu_keyboard.add(
    KeyboardButton("📋 Напоминания")
)

def get_weather_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("🌦 Погода сегодня", "🔔 Уведомлять о погоде")
    keyboard.row("⚙️ Настройки погоды")  # Убедитесь, что текст точно совпадает
    keyboard.row("↩️ Назад в меню")
    return keyboard

confirmation_pending = {}
id_counter = 1  # глобальный счётчик напоминаний
job_counter = 1
temp_repeating = {}

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Переменная для хранения интервала (по умолчанию 30 минут)
confirmation_interval = 30

# Команда /help - отправка инструкции в PDF
def send_help(message):
    try:
        # Убедитесь, что путь к файлу правильный
        with open("instruction_extended.txt", "rb") as txt_file:
            bot.send_document(message.chat.id, txt_file)
    except FileNotFoundError:
        bot.send_message(message.chat.id, "Извините, файл с инструкцией не найден.")

# Команда /set_confirmation_interval - изменение интервала для подтверждения
@bot.message_handler(commands=['set_confirmation_interval'])
def set_confirmation_interval(message):
    bot.send_message(message.chat.id, "Введите новый интервал в минутах для подтверждения (например, 15, 30, 45):")
    bot.register_next_step_handler(message, process_interval_input)

def process_interval_input(message):
    global confirmation_interval
    try:
        new_interval = int(message.text.strip())
        if new_interval <= 0:
            raise ValueError("Интервал должен быть положительным числом.")
        confirmation_interval = new_interval
        bot.send_message(message.chat.id, f"Интервал для подтверждения изменён на {confirmation_interval} минут(ы).")
    except ValueError as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}. Пожалуйста, введите правильное число.")
        bot.register_next_step_handler(message, process_interval_input)

# Пример использования изменения интервала при добавлении подтверждения
@bot.message_handler(func=lambda message: message.text == "✅ Подтв.")
def toggle_repeat_mode(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=menu_keyboard)
        return

    bot.send_message(message.chat.id, "Введите номера напоминаний, для которых включить/отключить подтверждение.", reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, process_repeat_selection)

def process_repeat_selection(message):
    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)

    user_id = message.from_user.id
    ensure_user_exists(user_id)

    try:
        parts = message.text.strip().split()
        indices = list(map(int, [x for x in parts if x.isdigit()]))
        sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])

        for i in indices:
            if 0 < i <= len(sorted_reminders):
                rem = sorted_reminders[i - 1]
                # Переключаем: если уже был включён — отключаем
                if rem.get("needs_confirmation"):
                    rem["needs_confirmation"] = False
                    rem.pop("repeat_interval", None)  # Убираем повторение, если оно было
                else:
                    rem["needs_confirmation"] = True
                    # Устанавливаем интервал из переменной confirmation_interval
                    rem["repeat_interval"] = confirmation_interval

        save_reminders()
        bot.send_message(
            message.chat.id,
            f"✅ Обновлено! Повтор через {confirmation_interval} мин. (если включено)",
            reply_markup=menu_keyboard
        )
    except Exception as e:
        bot.send_message(message.chat.id, "Что-то пошло не так. Проверь формат и попробуй снова.", reply_markup=ReplyKeyboardMarkup())
        logger.error(f"[REPEAT_SELECTION ERROR] {e}")

scheduler = BackgroundScheduler()
scheduler.start()
reminders = {}

WEBHOOK_URL = 'https://din-js6l.onrender.com'  

bot.remove_webhook()
bot.set_webhook(url=WEBHOOK_URL)

from pytz import timezone, utc

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

moscow = timezone('Europe/Moscow')

# Обработчик команды /list_reminders
@bot.message_handler(commands=['list_reminders'])
def list_reminders(message):
    # Логика для отображения напоминаний
    reminders = get_all_reminders()  # Замените на вашу функцию получения напоминаний
    reminder_text = "\n".join([f"{i+1}. {reminder}" for i, reminder in enumerate(reminders)])
    bot.send_message(message.chat.id, reminder_text)

def back_to_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

def get_main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("🆕 Добавить", "🔁 Повтор")
    keyboard.row("🌤 Погода")
    keyboard.row("📋 Напоминания")
    return keyboard

def load_reminders():
    global reminders
    try:
        with open("reminders.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            for user_id, user_reminders in data.items():
                reminders[int(user_id)] = user_reminders
    except FileNotFoundError:
        print("Файл reminders.json не найден, начинаем с пустого списка.")

def save_reminders():
    with open("reminders.json", "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2, default=str)

def restore_jobs():
    for user_id, user_reminders in reminders.items():
        for rem in user_reminders:
            if rem["is_repeating"]:
                scheduler.add_job(
                    send_reminder,
                    trigger='interval',
                    days=1 if "день" in rem["text"] else 7,
                    start_date=rem["time"],
                    args=[int(user_id), rem["text"].split(" (повт.")[0], rem["time"].split("T")[1][:5], rem["job_id"]],
                    id=rem["job_id"]
                )
            else:
                rem_time = datetime.fromisoformat(rem["time"])
                if rem_time > datetime.utcnow():
                    scheduler.add_job(
                        send_reminder,
                        trigger='date',
                        run_date=rem_time,
                        args=[int(user_id), rem["text"], rem_time.strftime("%H:%M"), rem["job_id"]],
                        id=rem["job_id"]
                    )

def get_hourly_forecast(city: str) -> dict:
    """
    Получает прогноз погоды на указанные часы (08:00, 13:00, 17:00, 20:00)
    :param city: Название города
    :return: Словарь с прогнозами {время: данные}
    """
    api_key = '71d3d00aad6c943eb72ea5938056106d'  # Ваш API-ключ
    base_url = 'https://api.openweathermap.org/data/2.5/forecast'
    
    params = {
        'q': city,
        'units': 'metric',
        'lang': 'ru',
        'appid': api_key,
        'cnt': 24  # Получаем больше прогнозов для поиска нужных часов
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        forecast_data = response.json()
        
        target_times = {'08:00', '13:00', '17:00', '20:00'}
        hourly_forecast = {}
        today = datetime.now().date()
        
        for item in forecast_data['list']:
            forecast_time = datetime.fromtimestamp(item['dt'])
            time_str = forecast_time.strftime('%H:%M')
            
            # Берем только прогнозы на сегодня и для нужных часов
            if forecast_time.date() == today and time_str in target_times:
                hourly_forecast[time_str] = {
                    'time': time_str,
                    'temp': round(item['main']['temp']),
                    'feels_like': round(item['main']['feels_like']),
                    'description': item['weather'][0]['description'].capitalize(),
                    'wind_speed': item['wind']['speed'],
                    'humidity': item['main']['humidity'],
                    'pressure': item['main']['pressure'],
                    'icon': item['weather'][0]['icon']
                }
        
        # Если не нашли все нужные часы, берем ближайшие доступные
        if len(hourly_forecast) < 4:
            remaining_times = target_times - set(hourly_forecast.keys())
            if remaining_times:  # Проверяем, что есть времена, которые нужно заполнить
                for item in forecast_data['list']:
                    forecast_time = datetime.fromtimestamp(item['dt'])
                    if forecast_time.date() == today:
                        time_str = forecast_time.strftime('%H:%M')
                        if time_str not in hourly_forecast:
                            closest_time = min(remaining_times,
                                             key=lambda x: abs(datetime.strptime(x, '%H:%M').hour - forecast_time.hour))
                            if closest_time not in hourly_forecast:
                                hourly_forecast[closest_time] = {
                                    'time': closest_time,
                                    'temp': round(item['main']['temp']),
                                    'feels_like': round(item['main']['feels_like']),
                                    'description': item['weather'][0]['description'].capitalize(),
                                    'wind_speed': item['wind']['speed'],
                                    'humidity': item['main']['humidity'],
                                    'pressure': item['main']['pressure'],
                                    'icon': item['weather'][0]['icon']
                                }
                                remaining_times.remove(closest_time)
                                if not remaining_times:
                                    break
        
        return hourly_forecast
    
    except requests.RequestException as e:
        print(f'Ошибка при запросе погоды: {e}')
        return {}
    except (KeyError, ValueError) as e:
        print(f'Ошибка обработки данных: {e}')
        return {}


DEFAULT_NOTIFICATION_TIME = "7.30"  # Время уведомлений по умолчанию
user_weather_notifications = {}  # Хранит настройки уведомлений: {"user_id": {"enabled": True/False, "time": "7.30"}}

# === 5. Блок служебных функций ===
def ensure_user_exists(user_id):
    if user_id not in reminders:
        reminders[user_id] = []


from telebot.types import BotCommand, BotCommandScopeChatMember

ADMIN_ID = 941791842  # замени на свой Telegram ID

def send_help(message):
    # Устанавливаем команды, которые будут отображаться в меню бота

    bot.send_message(message.chat.id, "Вот список доступных команд:")

@bot.message_handler(commands=['restart'])
def restart_command(message):
    user_id = message.from_user.id

    # Очистка временных данных, если используешь
    confirmation_pending.pop(user_id, None)

    bot.send_message(
        message.chat.id,
        "🔄 Бот перезапущен. Добро пожаловать! Используйте команды или меню, чтобы продолжить.",
        reply_markup=menu_keyboard
    )

from datetime import datetime

def save_user_info(user):
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        users = {}

    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

def load_weather_notifications():
    global user_weather_notifications
    try:
        with open('weather_notifications.json', 'r') as f:
            user_weather_notifications = json.load(f)
    except FileNotFoundError:
        user_weather_notifications = {}

def save_weather_notifications():
    with open('weather_notifications.json', 'w') as f:
        json.dump(user_weather_notifications, f)

def parse_time_input(time_str):
    """Парсит введенное время в формате ЧЧ.ММ (MSK) и возвращает часы и минуты"""
    try:
        # Заменяем возможные запятые на точки для надежности
        time_str = time_str.replace(',', '.')
        hours, minutes = map(int, time_str.split('.'))
        
        # Проверяем валидность времени
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours, minutes
        else:
            return None
    except:
        return None

def schedule_daily_weather(user_id, time_str=DEFAULT_NOTIFICATION_TIME):
    try:
        # Удаляем старые задания для этого пользователя
        for job in scheduler.get_jobs():
            if job.id == f"weather_{user_id}":
                job.remove()
        
        # Парсим время
        hours, minutes = parse_time_input(time_str)
        if hours is None or minutes is None:
            raise ValueError("Invalid time format")
        
        # Создаем новое задание
        scheduler.add_job(
            send_daily_weather,
            trigger='cron',
            hour=hours,
            minute=minutes,
            args=[user_id],
            id=f"weather_{user_id}",
            timezone=moscow
        )
    except Exception as e:
        logger.error(f"Error scheduling weather for user {user_id}: {e}")

def send_daily_weather(user_id):
    try:
        API_KEY = "71d3d00aad6c943eb72ea5938056106d"
        city = user_weather_settings.get(str(user_id), {}).get('city', 'Москва')
        
        weather_data = get_cached_weather(API_KEY, city)
        
        if not weather_data:
            logger.error(f"Weather data not available for user {user_id}")
            return
        
        current = weather_data['list'][0]
        current_time = datetime.fromtimestamp(current['dt']).strftime('%H:%M')
        
        response = [
            f"🌤 <b>Ежедневный прогноз погоды в {city}</b>",
            f"<i>Обновлено: {current_time}</i>",
            "",
            f"<b>Сейчас:</b> {current['weather'][0]['description'].capitalize()}",
            f"🌡 Температура: {round(current['main']['temp'])}°C",
            f"💨 Ветер: {current['wind']['speed']} м/с",
            f"💧 Влажность: {current['main']['humidity']}%",
            "",
            "<b>Прогноз на сегодня:</b>"
        ]

        for forecast in weather_data['list'][1:8]:
            time = datetime.fromtimestamp(forecast['dt']).strftime('%H:%M')
            temp = round(forecast['main']['temp'])
            desc = forecast['weather'][0]['description']
            response.append(f"🕒 {time}: {temp}°C, {desc}")

        bot.send_message(
            user_id,
            "\n".join(response),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error sending daily weather to {user_id}: {e}")

# === 2. Блок общих команд ===
@bot.message_handler(commands=['start', 'help'])
def handle_start_help(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    if message.text.startswith('/start'):
        ensure_user_exists(message.from_user.id)
        save_user_info(message.from_user)
        bot.send_message(message.chat.id, "Главное меню:\nВыберите действие:", reply_markup=menu_keyboard)
    elif message.text.startswith('/help'):
        try:
            with open("instruction_extended.txt", "rb") as txt_file:
                bot.send_document(message.chat.id, txt_file, reply_markup=menu_keyboard)
        except FileNotFoundError:
            bot.send_message(message.chat.id, "Извините, файл с инструкцией не найден.", reply_markup=menu_keyboard)
def start_command(message):
    user_id = message.from_user.id

    # Обеспечиваем, что пользователь записан
    ensure_user_exists(user_id)
    save_user_info(message.from_user)

    # Сбрасываем возможные "ожидающие шаги"
    bot.clear_step_handler_by_chat_id(message.chat.id)

    # Возвращаем главное меню
    bot.send_message(
        message.chat.id,
        "Главное меню:\nВыберите действие:",
        reply_markup=menu_keyboard
    )

@bot.message_handler(regexp=r"^/done_[\w\-]+$")
def handle_done_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    job_id = message.text.replace("/done_", "").strip()

    for rem in reminders.get(user_id, []):
        if str(rem["id"]) == job_id:
            try:
                scheduler.remove_job(rem["job_id"])
            except:
                pass
            reminders[user_id].remove(rem)
            save_reminders()
            bot.send_message(message.chat.id, f"✅ Напоминание «{rem['text']}» подтверждено и удалено.", reply_markup=menu_keyboard)
            return

    bot.send_message(message.chat.id, "Напоминание не найдено или уже подтверждено.", reply_markup=menu_keyboard)


@bot.message_handler(regexp=r"^/skip_[\w\-]+$")
def handle_skip_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    job_id = message.text.replace("/skip_", "").strip()

    for rem in reminders.get(user_id, []):
        if str(rem["id"]) == job_id:
            interval = rem.get("repeat_interval", confirmation_interval)
            new_job_id = str(uuid.uuid4())  # технический ID для планировщика

            rem["time"] = datetime.utcnow() + timedelta(minutes=interval)
            rem["job_id"] = new_job_id

            scheduler.add_job(
                send_reminder,
                trigger='date',
                run_date=rem["time"],
                args=[user_id, rem["text"], rem["time"].strftime("%H:%M"), new_job_id],
                id=new_job_id
            )
            save_reminders()
            bot.send_message(message.chat.id, f"🔁 Перенесено на {interval} минут: {rem['text']}", reply_markup=menu_keyboard)
            return

    bot.send_message(message.chat.id, "Напоминание не найдено или уже обработано.", reply_markup=menu_keyboard)

@bot.message_handler(func=lambda message: message.text == "🆕 Добавить")
def handle_add(message):
    add_reminder(message)  # Вызывает уже существующую функцию
    print("Добавление нажато")  # или logger.info(...)

@bot.message_handler(func=lambda message: message.text == "🔁 Повтор")
def handle_repeat_button(message):
    bot.send_message(message.chat.id, "🔧 Функция повтора пока не работает. Мы уже работаем над этим!", reply_markup=menu_keyboard)
    return
    # остальной код временно не выполняется

@bot.message_handler(func=lambda message: message.text == "🗑 Удалить")
def handle_delete(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=menu_keyboard)
        return

    bot.send_message(message.chat.id, "Введите номера напоминаний для удаления (через пробел):", reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, process_remove_input)


@bot.message_handler(func=lambda message: message.text == "✅ Подтв.")
def handle_confirm(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=menu_keyboard)
        return

    bot.send_message(message.chat.id, "Введите номера напоминаний, для которых включить/отключить подтверждение (через пробел):", reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, process_repeat_selection)

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню")
def back_to_main_menu(message):
    bot.send_message(
        message.chat.id,
        "Главное меню:",
        reply_markup=get_main_menu_keyboard()
    )

ADMIN_ID = 941791842  # замени на свой

@bot.message_handler(commands=['devmode'])
def show_users(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Эта команда доступна только администратору.")
        return

    try:
        with open("users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        bot.send_message(message.chat.id, "📂 Нет зарегистрированных пользователей.")
        return

    if not users:
        bot.send_message(message.chat.id, "😶 Пользователей не найдено.")
        return

    response = ""
    for uid, data in users.items():
        uname = f"@{data['username']}" if data.get('username') else data.get("first_name", "❓")
        joined = data.get("joined_at", "время не указано")
        response += f"{uname}, [{joined}]\n"

    bot.send_message(message.chat.id, response, reply_markup=menu_keyboard)

@bot.message_handler(commands=['ping'])
def test_ping(message):
    bot.send_message(message.chat.id, "Пинг ок!", reply_markup=menu_keyboard)

@bot.message_handler(commands=['dump'])
def dump_reminders(message):
    try:
        with open("reminders.json", "r", encoding="utf-8") as f:
            data = f.read()
        # Отправляем в виде кода, чтобы сохранить формат
        bot.send_message(message.chat.id, f"```json\n{data}\n```", parse_mode="Markdown")
    except FileNotFoundError:
        bot.send_message(message.chat.id, "Файл reminders.json не найден.", reply_markup=menu_keyboard)

@bot.message_handler(func=lambda message: message.text == "Добавить напоминание")
# === 4. Блок функций для напоминаний ===
def add_reminder(message):
    bot.send_message(message.chat.id, "Введите напоминание в формате ЧЧ.ММ *событие* или ДД.ММ ЧЧ.ММ *событие*.", 	reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, process_reminder)

def process_reminder(message):
    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)
    
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    now = datetime.now(moscow)

    try:
        # Обработка формата даты/времени
        full_match = re.match(r'^(\d{1,2})\.(\d{1,2}) (\d{1,2})\.(\d{2}) (.+)', message.text)
        if full_match:
            day, month, hour, minute, event = full_match.groups()
            reminder_datetime_moscow = moscow.localize(datetime(
                year=now.year, month=int(month), day=int(day),
                hour=int(hour), minute=int(minute)
            ))
        else:
            time_match = re.match(r'^(\d{1,2})\.(\d{2}) (.+)', message.text)
            if not time_match:
                raise ValueError
            hour, minute, event = time_match.groups()
            reminder_datetime_moscow = moscow.localize(datetime.combine(
                now.date(), datetime.strptime(f"{hour}.{minute}", "%H.%M").time()
            ))
            if reminder_datetime_moscow < now:
                reminder_datetime_moscow += timedelta(days=1)
        reminder_datetime = reminder_datetime_moscow.astimezone(utc)
        global job_counter
        global id_counter
        
        reminder_id = str(id_counter)
        id_counter += 1
        
        job_id = str(uuid.uuid4())  # это для планировщика, можно оставить

        
        reminders[user_id].append({
            "id": reminder_id,                # стабильный ID
            "job_id": job_id,                 # планировочный ID
            "time": reminder_datetime,       # или first_run_utc
            "text": event,                   # или event + " (повт. ...)"
            "is_repeating": False,           # или True
            "needs_confirmation": False      # или True
        })
        save_reminders()


        scheduler.add_job(
            send_reminder,
            trigger='date',
            run_date=reminder_datetime,
            args=[user_id, event, reminder_datetime.strftime("%H:%M"), job_id],
            id=job_id
        )

        # 🔥 Вот здесь ВОЗВРАТ К ГЛАВНОМУ МЕНЮ
        bot.send_message(
            message.chat.id,
            f"✅ Напоминание на {reminder_datetime_moscow.strftime('%d.%m %H:%M')} (MSK) — {event}",
            reply_markup=menu_keyboard
        )

    except Exception:
        bot.send_message(
            message.chat.id,
            "Неверный формат. Попробуйте снова.",
            reply_markup=back_to_menu_keyboard()
        )
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(message, process_reminder)
        
@bot.message_handler(func=lambda message: message.text == "📋 Напоминания")
def show_reminders(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=menu_keyboard)
        return

    sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])
    text = "Ваши напоминания:\n"

    for i, rem in enumerate(sorted_reminders, start=1):
        msk_time = rem["time"].astimezone(moscow)
        line = f"{i}. {msk_time.strftime('%d.%m %H:%M')} — {rem['text']}"

        if rem.get("is_repeating"):
            match = re.search(r"\(повт\. (.+?)\)", rem.get("text", ""))
            if match:
                interval_text = match.group(1)
                line += f" 🔁 ({interval_text})"

        if rem.get("needs_confirmation"):
            interval = rem.get("repeat_interval", confirmation_interval)
            line += f", 🚨 ({interval})"

        text += line + "\n"

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("✅ Подтв."), types.KeyboardButton("🗑 Удалить"))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))

    bot.send_message(message.chat.id, text, reply_markup=keyboard)

ADMIN_ID = 941791842  # замени на свой Telegram ID

@bot.message_handler(commands=['devmode'])
def show_users(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Эта команда доступна только администратору.")
        return

    try:
        with open("users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        bot.send_message(message.chat.id, "📂 Нет зарегистрированных пользователей.")
        return

    if not users:
        bot.send_message(message.chat.id, "😶 Пользователей не найдено.")
        return

    response = "👥 Пользователи:\n"
    for uid, data in users.items():
        name = data.get("first_name", "")
        uname = f"@{data['username']}" if data.get('username') else "(без username)"
        joined = data.get("joined_at", "время не указано")
        response += f"\n🆔 {uid} — {name} {uname}\n🕒 Зашёл: {joined}\n"

    bot.send_message(message.chat.id, response, reply_markup=menu_keyboard)


def process_reminder(message):
    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)
    
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    moscow = timezone('Europe/Moscow')
    now = datetime.now(moscow)

    try:
        # Паттерн с датой
        full_match = re.match(r'^(\d{1,2})\.(\d{1,2}) (\d{1,2})\.(\d{2}) (.+)', message.text)
        if full_match:
            day, month, hour, minute, event = full_match.groups()
            reminder_datetime_moscow = moscow.localize(datetime(
                year=now.year, month=int(month), day=int(day),
                hour=int(hour), minute=int(minute)
            ))
        else:
            # Паттерн только с временем
            time_match = re.match(r'^(\d{1,2})\.(\d{2}) (.+)', message.text)
            if not time_match:
                raise ValueError
            hour, minute, event = time_match.groups()
            reminder_datetime_moscow = moscow.localize(datetime.combine(now.date(), datetime.strptime(f"{hour}.{minute}", "%H.%M").time()))
            if reminder_datetime_moscow < now:
                reminder_datetime_moscow += timedelta(days=1)

        reminder_datetime = reminder_datetime_moscow.astimezone(utc)
        
        job_id = str(uuid.uuid4())  # это для планировщика, можно оставить

        global id_counter
        reminder_id = str(id_counter)
        id_counter += 1
        
        reminders[user_id].append({
            "id": reminder_id,
            "job_id": job_id,
            "time": reminder_datetime,
            "text": event,
            "is_repeating": False,
            "needs_confirmation": False
        })


        scheduler.add_job(
            send_reminder,
            trigger='date',
            run_date=reminder_datetime,
            args=[user_id, event, reminder_datetime.strftime("%H:%M"), job_id],
            id=job_id
        )

        bot.send_message(message.chat.id, f"Напоминание на {reminder_datetime_moscow.strftime('%d.%m %H:%M')} (MSK) — {event}", reply_markup=menu_keyboard)

    except Exception:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.", reply_markup=back_to_menu_keyboard())
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(message, process_reminder)

@bot.message_handler(func=lambda message: message.text == "Повторяющееся напоминание")
def add_repeating_reminder(message):
    bot.send_message(message.chat.id, "Введите время и событие в формате ЧЧ.ММ *событие*.", reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, ask_repeat_interval)

@bot.message_handler(func=lambda message: message.text == "🌤 Погода")
def handle_weather_menu(message):
    try:
        logger.info(f"Weather menu requested by {message.from_user.id}")
        bot.send_message(
            message.chat.id,
            "Выберите действие с погодой:",
            reply_markup=get_weather_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in weather menu: {e}")
        bot.send_message(
            message.chat.id,
            "⚠️ Произошла ошибка при обработке запроса.",
            reply_markup=get_main_menu_keyboard()
        )

@bot.message_handler(func=lambda message: message.text == "🌦 Погода сегодня")
def handle_today_weather(message):
    API_KEY = "71d3d00aad6c943eb72ea5938056106d"  # Ваш API-ключ
    
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # Получаем данные с кэшированием
        weather_data = get_cached_weather(API_KEY, "Москва")
        
        if not weather_data:
            raise Exception("Сервис погоды временно недоступен")

        # Текущая погода
        current = weather_data['list'][0]
        current_time = datetime.fromtimestamp(current['dt']).strftime('%H:%M')
        
        # Формируем ответ
        response = [
            f"🌤 <b>Погода в Москве</b>",
            f"<i>Обновлено: {current_time}</i>",
            "",
            f"<b>Сейчас:</b> {current['weather'][0]['description'].capitalize()}",
            f"🌡 Температура: {round(current['main']['temp'])}°C",
            f"💨 Ветер: {current['wind']['speed']} м/с",
            f"💧 Влажность: {current['main']['humidity']}%",
            "",
            "<b>Прогноз на сегодня:</b>"
        ]

        # Добавляем прогноз по часам
        for forecast in weather_data['list'][1:8]:  # Следующие 21 час (3 часа * 7)
            time = datetime.fromtimestamp(forecast['dt']).strftime('%H:%M')
            temp = round(forecast['main']['temp'])
            desc = forecast['weather'][0]['description']
            response.append(f"🕒 {time}: {temp}°C, {desc}")

        bot.send_message(
            message.chat.id,
            "\n".join(response),
            parse_mode='HTML',
            reply_markup=get_weather_menu_keyboard()
        )

    except Exception as e:
        logger.error(f"[WEATHER ERROR] {str(e)}")
        bot.send_message(
            message.chat.id,
            "⚠️ Не удалось получить данные о погоде. Попробуйте через несколько минут.",
            reply_markup=get_weather_menu_keyboard()
        )

@bot.message_handler(func=lambda message: message.text == "🔄 Обновить погоду")
def handle_refresh_weather(message):
    handle_today_weather(message)  # Просто вызываем тот же обработчик

@bot.message_handler(func=lambda message: message.text == "↩️ Назад")
def back_to_weather_menu(message):
    bot.send_message(
        message.chat.id,
        "Меню погоды:",
        reply_markup=get_weather_menu_keyboard()
    )
@bot.message_handler(func=lambda message: message.text == "🔔 Уведомлять о погоде")
def handle_weather_notifications(message):
    user_id = str(message.from_user.id)
    
    # Инициализируем настройки, если их нет
    if user_id not in user_weather_notifications:
        user_weather_notifications[user_id] = {
            "enabled": False,
            "time": DEFAULT_NOTIFICATION_TIME
        }
    
    status = user_weather_notifications[user_id].get('enabled', False)
    time = user_weather_notifications[user_id].get('time', DEFAULT_NOTIFICATION_TIME)
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("/change_weather_status"))
    keyboard.add(types.KeyboardButton("/change_weather_time"))
    keyboard.add(types.KeyboardButton("↩️ Назад в меню погоды"))
    
    bot.send_message(
        message.chat.id,
        f"Текущий статус уведомлений о погоде: {'✅ Включены' if status else '❌ Выключены'}\n"
        f"Время уведомлений: {time} (MSK)\n\n"
        "Используйте команды:\n"
        "/change_weather_status - переключить статус\n"
        "/change_weather_time - изменить время уведомлений",
        reply_markup=keyboard
    )

@bot.message_handler(commands=['change_weather_status'])
def change_weather_status(message):
    user_id = str(message.from_user.id)
    
    # Если у пользователя ещё нет настроек, создаём их
    if user_id not in user_weather_notifications:
        user_weather_notifications[user_id] = {
            "enabled": False,
            "time": DEFAULT_NOTIFICATION_TIME  # "7.30" по умолчанию
        }
    
    # Меняем статус на противоположный
    new_status = not user_weather_notifications[user_id]['enabled']
    user_weather_notifications[user_id]['enabled'] = new_status
    
    # Если уведомления включены — запускаем ежедневную рассылку
    if new_status:
        time_str = user_weather_notifications[user_id]['time']
        schedule_daily_weather(int(user_id), time_str)
        response = "✅ Уведомления о погоде **включены**"
    else:
        # Если выключены — удаляем задание из планировщика
        job_id = f"weather_{user_id}"
        for job in scheduler.get_jobs():
            if job.id == job_id:
                job.remove()
        response = "❌ Уведомления о погоде **выключены**"
    
    # Сохраняем изменения в файл
    save_weather_notifications()
    
    # Отправляем ответ пользователю
    bot.send_message(
        message.chat.id,
        response,
        reply_markup=get_weather_menu_keyboard()
    )
@bot.message_handler(commands=['change_weather_time'])
def change_weather_time(message):
    user_id = str(message.from_user.id)
    
    if user_id not in user_weather_notifications:
        user_weather_notifications[user_id] = {
            "enabled": False,
            "time": DEFAULT_NOTIFICATION_TIME
        }
    
    bot.send_message(
        message.chat.id,
        f"Текущее время уведомлений: {user_weather_notifications[user_id]['time']} (MSK)\n"
        "Введите новое время в формате ЧЧ.ММ (например, 8.00 или 7.30):",
        reply_markup=back_to_weather_settings_keyboard()
    )
    bot.register_next_step_handler(message, process_weather_time_input)
    
    # Меняем статус на противоположный
    new_status = not user_weather_notifications[user_id].get('enabled', False)
    user_weather_notifications[user_id]['enabled'] = new_status
    
    if new_status:
        time_str = user_weather_notifications[user_id].get('time', DEFAULT_NOTIFICATION_TIME)
        schedule_daily_weather(int(user_id), time_str)
        response = "✅ Уведомления о погоде включены"
    else:
        # Удаляем задание, если есть
        for job in scheduler.get_jobs():
            if job.id == f"weather_{user_id}":
                job.remove()
        response = "❌ Уведомления о погоде выключены"
    
    save_weather_notifications()
    bot.send_message(message.chat.id, response, reply_markup=get_weather_menu_keyboard())


def process_weather_time_input(message):
    if message.text == "↩️ Назад в меню погоды":
        return back_to_weather_menu(message)
    
    user_id = str(message.from_user.id)
    time_input = message.text.strip()
    
    # Проверяем, не является ли ввод командой (начинается с /)
    if time_input.startswith('/'):
        bot.send_message(
            message.chat.id,
            "❌ Пожалуйста, введите время в формате ЧЧ.ММ (например, 7.30 или 8.00)",
            reply_markup=back_to_weather_settings_keyboard()
        )
        bot.register_next_step_handler(message, process_weather_time_input)
        return
    
    parsed_time = parse_time_input(time_input)
    
    if parsed_time:
        hours, minutes = parsed_time
        # Форматируем время обратно в строку (7.30 вместо 7.3)
        time_str = f"{hours}.{minutes:02d}"
        user_weather_notifications[user_id]['time'] = time_str
        
        # Если уведомления включены, перепланируем
        if user_weather_notifications[user_id].get('enabled', False):
            schedule_daily_weather(int(user_id), time_str)
        
        save_weather_notifications()
        bot.send_message(
            message.chat.id,
            f"✅ Время уведомлений изменено на {time_str} (MSK)",
            reply_markup=get_weather_menu_keyboard()
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Неверный формат времени. Используйте ЧЧ.ММ (например, 7.30 или 8.00)",
            reply_markup=back_to_weather_settings_keyboard()
        )
        bot.register_next_step_handler(message, process_weather_time_input)

@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки погоды")
def handle_weather_settings(message):
    bot.send_message(
        message.chat.id,
        "Пока что доступна только Москва 😔😔😔",
        reply_markup=get_weather_menu_keyboard()
    )
    
@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню погоды")
def back_to_weather_menu(message):
    bot.send_message(
        message.chat.id,
        "Меню погоды:",
        reply_markup=get_weather_menu_keyboard()
    )
    
    try:
        response = requests.get(test_url)
        if response.status_code == 200:
            # Сохраняем настройки для пользователя
            if user_id not in user_weather_settings:
                user_weather_settings[user_id] = {}
            user_weather_settings[user_id]['city'] = city
            
            # Можно сохранить в файл для постоянного хранения
            save_weather_settings()
            
            bot.send_message(
                message.chat.id,
                f"✅ Город успешно изменен на {city}",
                reply_markup=get_weather_settings_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ Не удалось найти такой город. Попробуйте еще раз:",
                reply_markup=back_to_weather_settings_keyboard()
            )
            bot.register_next_step_handler(message, process_city_input)
    except Exception as e:
        logger.error(f"Error checking city: {e}")
        bot.send_message(
            message.chat.id,
            "⚠️ Произошла ошибка при проверке города. Попробуйте позже.",
            reply_markup=get_weather_settings_keyboard()
        )

@bot.message_handler(func=lambda message: message.text == "🏙 Изменить город")
def handle_change_city(message):
    print ("Пока что доступна только Москва 😔😔😔")
        
def ask_repeat_interval(message):

    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)
    
    user_id = message.from_user.id
    try:
        time_match = re.match(r'^(\d{1,2})\.(\d{2}) (.+)', message.text)
        if not time_match:
            raise ValueError

        hour, minute, event = time_match.groups()
        
        temp_repeating[user_id] = {
            "time_str": f"{hour}.{minute}",
            "event": event
        }

        # Предлагаем выбор интервала
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("Каждый день"), types.KeyboardButton("Каждую неделю"))
        bot.send_message(message.chat.id, "Как часто повторять?", reply_markup=keyboard)
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(message, process_repeating_interval)

    except:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.")
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(message, add_repeating_reminder)


def process_repeating_interval(message):

    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)
    
    user_id = message.from_user.id
    data = temp_repeating.get(user_id)
    
    if not data:
        bot.send_message(message.chat.id, "Что-то пошло не так. Начните заново.")
        return
    
    time_str = data["time_str"]
    event = data["event"]
    del temp_repeating[user_id]  # Удалить после использования

    
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    interval_input = message.text.strip().lower()

    interval = None
    if interval_input == "каждый день":
        interval = "день"
    elif interval_input == "каждую неделю":
        interval = "неделя"
    else:
        bot.send_message(message.chat.id, "Непонятный интервал. Попробуйте снова.")
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(message, process_repeating_interval)
        return

    try:
        moscow = timezone('Europe/Moscow')
        now = datetime.now(moscow)
        time_obj = datetime.strptime(time_str, "%H.%M").time()
        first_run = moscow.localize(datetime.combine(now.date(), time_obj))

        if first_run < now:
            first_run += timedelta(days=1)

        first_run_utc = first_run.astimezone(utc)
        global job_counter
        global id_counter
        reminder_id = str(id_counter)
        id_counter += 1
        
        job_id = str(uuid.uuid4())  # это для планировщика, можно оставить

        

        if interval == 'день':
            scheduler.add_job(send_reminder, 'interval', days=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)
        elif interval == 'неделя':
            scheduler.add_job(send_reminder, 'interval', weeks=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)

        
        reminder_id = str(id_counter)
        id_counter += 1
        
        reminders[user_id].append({
            "id": reminder_id,
            "job_id": job_id,
            "time": reminder_datetime,
            "text": event,
            "is_repeating": False,
            "needs_confirmation": False
        })

        if interval == "день":
            form = "каждый день"
        else:
            form = "каждую неделю"
        
        bot.send_message(
            message.chat.id,
            f"✅ Повторяющееся напоминание на {first_run.strftime('%d.%m %H:%M')} (MSK) — {event} {form}",
            reply_markup=menu_keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка в повторяющемся напоминании: {e}")
        bot.send_message(message.chat.id, "Что-то пошло не так. Попробуйте снова.", reply_markup=ReplyKeyboardMarkup())

def process_remove_input(message):

    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)
    
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    try:
        reminder_indices = list(map(int, re.findall(r'\d+', message.text)))
        sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])
        reminders_to_remove = [sorted_reminders[i - 1] for i in reminder_indices if 0 < i <= len(sorted_reminders)]
        for rem in reminders_to_remove:
            for job in scheduler.get_jobs():
                if job.id == rem["job_id"]:
                    job.remove()
            reminders[user_id].remove(rem)
        
        save_reminders()
        bot.send_message(message.chat.id, "✅ Напоминания удалены.", reply_markup=menu_keyboard)

    except Exception:
        bot.send_message(message.chat.id, "Некорректный ввод, отмена удаления.", reply_markup=ReplyKeyboardMarkup())

def send_reminder(user_id, event, time, job_id):
    logger.info(f"[REMINDER] STARTED for user {user_id} | Event: {event} | Time: {time} | Job ID: {job_id}")

    try:
        reminder_time_utc = datetime.utcnow()
        reminder_time_msk = utc.localize(reminder_time_utc).astimezone(moscow).strftime('%H:%M')

        keyboard = None
        text_suffix = ""

        for rem in reminders.get(user_id, []):
            if rem["job_id"] == job_id and rem.get("needs_confirmation"):
                confirmation_pending[user_id] = {
                    "job_id": job_id,
                    "text": event
                }
                
                text_suffix = (
                    f"\n\nНажмите, если выполнили:\n"
                    f"/done_{rem['id']}\n"
                    f"или пропустите:\n"
                    f"/skip_{rem['id']}"
                )

                break

        msg = bot.send_message(
            user_id,
            f"🔔 Напоминание: {event} (в {reminder_time_msk} по МСК){text_suffix}\n\n[#ID:{rem['id']}]",
            reply_markup=menu_keyboard
        )

        logger.info(f"[REMINDER] Sent to user {user_id}")

    except Exception as e:
        logger.error(f"[REMINDER ERROR] {e}")

    # Обработка повтора
    for rem in reminders.get(user_id, []):
        if str(rem["job_id"]) == job_id:
            if rem.get("is_repeating"):
                return
            if rem.get("needs_confirmation"):
                interval = rem.get("repeat_interval", confirmation_interval)
                global job_counter
                
                job_id = str(uuid.uuid4())  # это для планировщика, можно оставить


                scheduler.add_job(
                    send_reminder,
                    trigger='date',
                    run_date=datetime.utcnow() + timedelta(minutes=interval),
                    args=[user_id, event, time, new_job_id],
                    id=new_job_id
                )
                rem["job_id"] = new_job_id
                save_reminders()
            else:
                reminders[user_id] = [r for r in reminders[user_id] if r["job_id"] != job_id]
                save_reminders()

# === 6. Блок Webhook и self-ping ===
@app.route("/", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    return "Invalid request", 400

@app.route("/", methods=["GET"])
def root():
    return "It works!", 200

import threading
import requests
from time import sleep

def self_ping():
    while True:
        try:
            response = requests.head(WEBHOOK_URL)
            print(f"[PING] Status: {response.status_code}")
        except Exception as e:
            print(f"[PING ERROR] {e}")
        sleep(60)

@bot.message_handler(func=lambda message: message.text == "✅ Подтв.")
def toggle_repeat_mode(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=menu_keyboard)
        return

    bot.send_message(message.chat.id, "Введите номера напоминаний, для которых включить/отключить подтверждение.", reply_markup=back_to_menu_keyboard())
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.register_next_step_handler(message, process_repeat_selection)

def process_repeat_selection(message):
    if message.text == "↩️ Назад в меню":
        return back_to_main_menu(message)

    user_id = message.from_user.id
    ensure_user_exists(user_id)

    try:
        parts = message.text.strip().split()
        indices = list(map(int, [x for x in parts if x.isdigit()]))
        sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])

        for i in indices:
            if 0 < i <= len(sorted_reminders):
                rem = sorted_reminders[i - 1]
                # Переключаем: если уже был включён — отключаем
                if rem.get("needs_confirmation"):
                    rem["needs_confirmation"] = False
                    rem.pop("repeat_interval", None)  # Убираем повторение, если оно было
                else:
                    rem["needs_confirmation"] = True  # Устанавливаем необходимость подтверждения

        save_reminders()
        bot.send_message(
            message.chat.id,
            f"✅ Обновлено! Повтор через {confirmation_interval} мин. (если включено)",
            reply_markup=menu_keyboard
        )
    except Exception as e:
        bot.send_message(message.chat.id, "Что-то пошло не так. Проверь формат и попробуй снова.", reply_markup=ReplyKeyboardMarkup())
        logger.error(f"[REPEAT_SELECTION ERROR] {e}")

@bot.message_handler(commands=['done'])
def confirm_done(message):
    parts = message.text.strip().split()
    if len(parts) != 2:
        bot.send_message(message.chat.id, "Формат: /done <job_id>")
        return

    job_id = parts[1]
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    for rem in reminders[user_id]:
        if str(rem["job_id"]) == job_id:
            rem["needs_confirmation"] = False
            rem.pop("repeat_interval", None)
            try:
                scheduler.remove_job(job_id)
            except:
                pass
            save_reminders()
            bot.send_message(message.chat.id, f"✅ Напоминание «{rem['text']}» подтверждено и больше не будет повторяться.")
            return

    bot.send_message(message.chat.id, "❌ Напоминание не найдено или уже подтверждено.")

@bot.message_handler(commands=['interval'])
def show_confirmation_interval(message):
    bot.send_message(
        message.chat.id,
        f"⏱ Текущий интервал для подтверждения: {confirmation_interval} минут",
        reply_markup=menu_keyboard
    )

@bot.message_handler(func=lambda message: message.text == "✅ Подтвердить")
def handle_confirm(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)

    # Проверяем, есть ли сообщение, на которое нажата кнопка
    if not message.reply_to_message or "#ID:" not in message.reply_to_message.text:
        bot.send_message(message.chat.id, "Невозможно подтвердить: не найдено напоминание.", reply_markup=menu_keyboard)
        return

    # Извлекаем job_id из текста сообщения
    match = re.search(r"\[#ID:(.+?)\]", message.reply_to_message.text)
    if not match:
        bot.send_message(message.chat.id, "Ошибка при распознавании напоминания.", reply_markup=menu_keyboard)
        return

    job_id = match.group(1)

    # Ищем и удаляем напоминание
    for rem in reminders[user_id]:
        if str(rem["job_id"]) == job_id:
            try:
                scheduler.remove_job(job_id)
            except:
                pass
            reminders[user_id].remove(rem)
            save_reminders()
            bot.send_message(message.chat.id, f"✅ Напоминание «{rem['text']}» подтверждено и удалено.", reply_markup=menu_keyboard)
            return

    bot.send_message(message.chat.id, "Напоминание не найдено или уже подтверждено.", reply_markup=menu_keyboard)

@bot.message_handler(func=lambda message: message.text == "🚫 Пропустить")
def handle_skip(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    job_id = confirmation_pending.get(user_id)

    if not job_id:
        bot.send_message(message.chat.id, "Нет активного напоминания.", reply_markup=menu_keyboard)
        return

    for rem in reminders[user_id]:
        if str(rem["job_id"]) == job_id:
            interval = rem.get("repeat_interval", confirmation_interval)
            global id_counter
            reminder_id = str(id_counter)
            id_counter += 1
            
            new_job_id = str(uuid.uuid4())  # технический ID для планировщика
            
            rem["job_id"] = new_job_id        # обновляем планировочный ID
            rem["id"] = reminder_id           # сохраняем постоянный ID для команд



            rem["time"] = datetime.utcnow() + timedelta(minutes=interval)
            rem["job_id"] = new_job_id
            scheduler.add_job(
                send_reminder,
                trigger='date',
                run_date=rem["time"],
                args=[user_id, rem["text"], rem["time"].strftime("%H:%M"), new_job_id],
                id=new_job_id
            )
            save_reminders()
            bot.send_message(message.chat.id, f"🔁 Перенесено на {interval} минут: {rem['text']}")
            break

    confirmation_pending.pop(user_id, None)
    
# === 7. Главный блок запуска ===
if __name__ == "__main__":
    load_reminders()
    load_weather_settings()
    load_weather_notifications()  # Загружаем настройки уведомлений
    
    # Восстанавливаем запланированные уведомления
    for user_id, settings in user_weather_notifications.items():
        if settings.get('enabled', False):
            schedule_daily_weather(int(user_id), settings.get('time', DEFAULT_NOTIFICATION_TIME))
    
    restore_jobs()

    bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("help", "Отправить инструкцию"),
        BotCommand("set_confirmation_interval", "Установить интервал для подтверждения"),
        BotCommand("list_reminders", "Показать список напоминаний"),
        BotCommand("interval", "Показать текущий интервал подтверждения"),
        BotCommand("restart", "Перезапустить бота"),
        BotCommand("devmode", "Режим разработчика"),
        # Закомментированные команды не будут отображаться:
        # BotCommand("add_reminder", "Добавить одноразовое напоминание"),
        # BotCommand("set_repeating_reminder", "Добавить повторяющееся напоминание"),
        # BotCommand("manage_reminder", "Управлять напоминаниями"),
        # BotCommand("delete_reminder", "Удалить напоминание"),
        # BotCommand("ping", "Проверка работоспособности бота")
    ])

    ping_thread = threading.Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()
    app.run(host="0.0.0.0", port=10000)
