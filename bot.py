import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from pytz import timezone, utc
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand

BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_token_here")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

moscow = timezone("Europe/Moscow")
reminders = {}
confirmation_pending = {}
confirmation_interval = 30
temp_repeating = {}
ADMIN_ID = 941791842

menu_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
menu_keyboard.add(KeyboardButton("🆕 Добавить"), KeyboardButton("🔁 Повтор"))
menu_keyboard.add(KeyboardButton("📋 Напоминания"))

def ensure_user_exists(user_id):
    if user_id not in reminders:
        reminders[user_id] = []

def save_reminders():
    with open("reminders.json", "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2, default=str)

def load_reminders():
    global reminders
    try:
        with open("reminders.json", "r", encoding="utf-8") as f:
            reminders = json.load(f)
    except:
        reminders = {}

def save_user_info(user):
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        users = {}

    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {
            "username": getattr(user, "username", ""),
            "first_name": getattr(user, "first_name", ""),
            "last_name": getattr(user, "last_name", ""),
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    save_user_info(message.from_user)

    bot.set_my_commands([
        BotCommand("start", "Запуск бота"),
        BotCommand("help", "Помощь"),
        BotCommand("devmode", "Режим разработчика"),
        BotCommand("restart", "Очистить все напоминания")
    ])

    bot.send_message(message.chat.id, "Главное меню:
Выберите действие:", reply_markup=menu_keyboard)

@bot.message_handler(commands=['help'])
def send_help(message):
    try:
        with open("instruction_extended.txt", "rb") as txt_file:
            bot.send_document(message.chat.id, txt_file)
    except FileNotFoundError:
        bot.send_message(message.chat.id, "Извините, файл с инструкцией не найден.")

@bot.message_handler(commands=['restart'])
def restart_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    for rem in reminders.get(user_id, []):
        try:
            scheduler.remove_job(rem["job_id"])
        except:
            pass
    reminders[user_id] = []
    save_reminders()
    bot.send_message(message.chat.id, "🔄 Всё очищено. Возвращаю в главное меню.", reply_markup=menu_keyboard)

@bot.message_handler(commands=['devmode'])
def devmode(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Эта команда только для администратора.")
        return
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        users = {}

    if not users:
        bot.send_message(message.chat.id, "📂 Нет зарегистрированных пользователей.")
        return

    response = "👥 Пользователи:
"
    for uid, data in users.items():
        name = data.get("first_name", "")
        uname = f"@{data['username']}" if data.get("username") else "(без username)"
        joined = data.get("joined_at", "время не указано")
        response += f"
🆔 {uid} — {name} {uname}
🕒 Зашёл: {joined}
"
    bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda message: message.text in ["✅", "❌"])
def handle_confirmation(message):
    user_id = message.from_user.id
    job_id = confirmation_pending.get(user_id)
    if not job_id:
        bot.send_message(message.chat.id, "Нет активного напоминания.")
        return

    for rem in reminders[user_id]:
        if rem["job_id"] == job_id:
            if message.text == "✅":
                reminders[user_id].remove(rem)
                save_reminders()
                bot.send_message(message.chat.id, f"✅ Удалено: {rem['text']}", reply_markup=menu_keyboard)
            elif message.text == "❌":
                interval = rem.get("repeat_interval", confirmation_interval)
                new_time = datetime.utcnow() + timedelta(minutes=interval)
                rem["time"] = new_time
                rem["job_id"] = str(uuid.uuid4())
                scheduler.add_job(send_reminder, 'date', run_date=new_time, args=[user_id, rem["text"], rem["job_id"]], id=rem["job_id"])
                save_reminders()
                bot.send_message(message.chat.id, f"🔁 Перенесено: {rem['text']}", reply_markup=menu_keyboard)
            break
    confirmation_pending.pop(user_id, None)

def send_reminder(user_id, text, job_id):
    confirmation_pending[user_id] = job_id
    bot.send_message(user_id, f"🔔 Напоминание: {text}
Нажмите ✅ если выполнено, ❌ если перенести", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("✅"), KeyboardButton("❌")))

if __name__ == "__main__":
    load_reminders()
    app.run(host="0.0.0.0", port=10000)
