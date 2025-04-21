from flask import Flask, request
import telebot
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import uuid
import re
from telebot import types

temp_repeating = {}

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

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

def main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Добавить напоминание"))
    keyboard.add(types.KeyboardButton("Повторяющееся напоминание"))
    keyboard.add(types.KeyboardButton("Показать напоминания"))
    return keyboard

def back_to_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

def ensure_user_exists(user_id):
    if user_id not in reminders:
        reminders[user_id] = []


bot.set_my_commands([
    telebot.types.BotCommand("start", "Главное меню"),
    telebot.types.BotCommand("ping", "Проверить, жив ли бот"),
])

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    bot.send_message(message.chat.id, "ЙОУ! Выберите действие:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "↩️ Назад в меню")
def back_to_main_menu(message):
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu_keyboard())


@bot.message_handler(commands=['ping'])
def test_ping(message):
    bot.send_message(message.chat.id, "Пинг ок!")

@bot.message_handler(func=lambda message: message.text == "Добавить напоминание")
def add_reminder(message):
    bot.send_message(message.chat.id, "Введите напоминание в формате ЧЧ.ММ *событие* или ДД.ММ ЧЧ.ММ *событие*.", 	reply_markup=back_to_menu_keyboard())
    bot.register_next_step_handler(message, process_reminder)

def process_reminder(message):
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

        job_id = str(uuid.uuid4())
        reminders[user_id].append({
            "time": reminder_datetime,
            "text": event,
            "job_id": job_id,
            "is_repeating": False
        })

        scheduler.add_job(
            send_reminder,
            trigger='date',
            run_date=reminder_datetime,
            args=[user_id, event, reminder_datetime.strftime("%H:%M"), job_id],
            id=job_id
        )

        bot.send_message(message.chat.id, f"Напоминание на {reminder_datetime_moscow.strftime('%d.%m %H:%M')} (MSK) — {event}", reply_markup=main_menu_keyboard())

    except Exception:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.", reply_markup=back_to_menu_keyboard())
        bot.register_next_step_handler(message, process_reminder)

@bot.message_handler(func=lambda message: message.text == "Повторяющееся напоминание")
def add_repeating_reminder(message):
    bot.send_message(message.chat.id, "Введите время и событие в формате ЧЧ.ММ *событие*.", reply_markup=back_to_menu_keyboard())
    bot.register_next_step_handler(message, ask_repeat_interval)

def ask_repeat_interval(message):
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
        bot.register_next_step_handler(message, process_repeating_interval)

    except:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.")
        bot.register_next_step_handler(message, add_repeating_reminder)


def process_repeating_interval(message):

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

    time_str = data["time_str"]
    event = data["event"]

    interval = None
    if interval_input == "каждый день":
        interval = "день"
    elif interval_input == "каждую неделю":
        interval = "неделя"
    else:
        bot.send_message(message.chat.id, "Непонятный интервал. Попробуйте снова.")
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
        job_id = str(uuid.uuid4())

        if interval == 'день':
            scheduler.add_job(send_reminder, 'interval', days=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)
        elif interval == 'неделя':
            scheduler.add_job(send_reminder, 'interval', weeks=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)

        reminders[user_id].append({
            "time": first_run_utc,
            "text": event + f" (повт. {interval})",
            "job_id": job_id,
            "is_repeating": True
        })

        bot.send_message(message.chat.id,
                         f"Повторяющееся напоминание на {first_run.strftime('%d.%m %H:%M')} (MSK) — {event} каждую {interval}",
                         reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка в повторяющемся напоминании: {e}")
        bot.send_message(message.chat.id, "Что-то пошло не так. Попробуйте снова.", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "Показать напоминания")
def show_reminders(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=main_menu_keyboard())
        return

    sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])
    text = "Ваши напоминания:\n"
    for i, rem in enumerate(sorted_reminders, start=1):
        msk_time = rem["time"].astimezone(moscow)
        text += f"{i}. {msk_time.strftime('%d.%m %H:%M')} - {rem['text']}\n"
    text += "\nВведите номера напоминаний для удаления (через пробел):"

    bot.send_message(message.chat.id, text, reply_markup=back_to_menu_keyboard())
    bot.register_next_step_handler(message, process_remove_input)

def process_remove_input(message):
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

        bot.send_message(message.chat.id, "Напоминания удалены.", reply_markup=main_menu_keyboard())

    except Exception:
        bot.send_message(message.chat.id, "Некорректный ввод, отмена удаления.", reply_markup=main_menu_keyboard())

def send_reminder(user_id, event, time, job_id):
    logger.info(f"[REMINDER] STARTED for user {user_id} | Event: {event} | Time: {time} | Job ID: {job_id}")
    try:
        reminder_time_utc = datetime.utcnow()
        reminder_time_msk = utc.localize(reminder_time_utc).astimezone(moscow).strftime('%H:%M')

        bot.send_message(user_id, f"🔔 Напоминание: {event} (в {reminder_time_msk} по МСК)", reply_markup=main_menu_keyboard())
        logger.info(f"[REMINDER] Sent to user {user_id}")
    except Exception as e:
        logger.error(f"[REMINDER ERROR] {e}")

    if user_id in reminders:
        reminders[user_id] = [rem for rem in reminders[user_id] if rem["job_id"] != job_id or rem["is_repeating"]]

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

if __name__ == "__main__":
    ping_thread = threading.Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()
    app.run(host="0.0.0.0", port=10000)
