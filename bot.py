from flask import Flask, request
import telebot
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import uuid
import re
from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from telebot.types import ReplyKeyboardMarkup, KeyboardButton

selected_weekdays = {}
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def create_weekday_keyboard(user_id):
    selected = selected_weekdays.get(user_id, [])
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    buttons = []

    for i, day in enumerate(DAYS_RU):
        prefix = "✅ " if i in selected else ""
        buttons.append(types.InlineKeyboardButton(f"{prefix}{day}", callback_data=f"weekday_{i}"))

    keyboard.add(*buttons)
    if selected:
        keyboard.add(types.InlineKeyboardButton("✅ Готово", callback_data="weekdays_done"))
    else:
        keyboard.add(types.InlineKeyboardButton("🔒 Готово", callback_data="disabled"))

    return keyboard

menu_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
menu_keyboard.add(
    KeyboardButton("🆕 Добавить"),
    KeyboardButton("🔁 Повтор")
)
menu_keyboard.add(
    KeyboardButton("📋 Напоминания")
)

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

def back_to_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("↩️ Назад в меню"))
    return keyboard

import json

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


def ensure_user_exists(user_id):
    if user_id not in reminders:
        reminders[user_id] = []


from telebot.types import BotCommand, BotCommandScopeChatMember

ADMIN_ID = 941791842  # замени на свой Telegram ID

# Устанавливаем команды для всех пользователей
bot.set_my_commands([
    BotCommand("start", "Главное меню"),
    BotCommand("ping", "Проверка"),
    BotCommand("devmode", "Режим разработчика"),  # ← теперь доступна в меню всем
])


import json
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

@bot.message_handler(commands=['start'])
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

@bot.message_handler(func=lambda message: message.text == "🆕 Добавить")

def handle_add(message):
    add_reminder(message)  # Вызывает уже существующую функцию
    print("Добавление нажато")  # или logger.info(...)

@bot.message_handler(func=lambda message: message.text == "🔁 Повтор")
def handle_repeat(message):
    add_repeating_reminder(message)

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
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=menu_keyboard)

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

    response = "👥 Пользователи:\n"
    for uid, data in users.items():
        name = data.get("first_name", "❓")
        joined = data.get("joined_at", "время не указано")
        response += f"\n🆔 {uid} — {name}\n🕒 Зашёл: {joined}\n"

    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['ping'])
def test_ping(message):
    bot.send_message(message.chat.id, "Пинг ок!")

@bot.message_handler(commands=['dump'])
def dump_reminders(message):
    try:
        with open("reminders.json", "r", encoding="utf-8") as f:
            data = f.read()
        # Отправляем в виде кода, чтобы сохранить формат
        bot.send_message(message.chat.id, f"```json\n{data}\n```", parse_mode="Markdown")
    except FileNotFoundError:
        bot.send_message(message.chat.id, "Файл reminders.json не найден.")

@bot.message_handler(func=lambda message: message.text == "Добавить напоминание")
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
        ...

        # Сохраняем напоминание
        reminders[user_id].append({
            "time": reminder_datetime,
            "text": event,
            "job_id": job_id,
            "is_repeating": False,
            "needs_confirmation": False
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
            interval = rem.get("repeat_interval", 30)
            line += f", 🚨 ({interval})"

        text += line + "\n"

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🗑 Удалить"), types.KeyboardButton("✅ Подтв."))
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

    bot.send_message(message.chat.id, response)


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

        job_id = str(uuid.uuid4())
        reminders[user_id].append({
            "time": reminder_datetime,
            "text": event,
            "job_id": job_id,
            "is_repeating": False,
            "needs_confirmation": False
        })
        save_reminders()

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
    
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    interval_input = message.text.strip().lower()

    interval = None
    if interval_input == "каждый день":
        interval = "день"
    elif interval_input == "каждую неделю":
        selected_weekdays[message.from_user.id] = []
        bot.send_message(
            message.chat.id,
            "🗓 Выбери дни недели для повтора:\n(нажимай на кнопки, выбранные будут отмечены ✅)",
            reply_markup=create_weekday_keyboard(message.from_user.id)
        )
        return  # выход после отправки клавиатуры, дальше не идём
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
        job_id = str(uuid.uuid4())

        reminder = {
            "time": first_run_utc,
            "text": event + f" (повт. {interval})",
            "job_id": job_id,
            "is_repeating": True,
            "interval": interval,
            "needs_confirmation": needs_confirmation,
            "repeat_interval": 30,
            "id": job_id  # Можно использовать тот же ID
        }
        
        if interval == 'день':
            scheduler.add_job(send_reminder, 'interval', days=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)
        elif interval == 'неделя':
            scheduler.add_job(send_reminder, 'interval', weeks=1, start_date=first_run_utc,
                              args=[user_id, event, time_str, job_id], id=job_id)
            if needs_confirmation:
                scheduler.add_job(
                    repeat_reminder_check,
                    'interval',
                    minutes=reminder["repeat_interval"] or 30,
                    args=[reminder, context],
                    id=f"repeat_{reminder['id']}",
                    replace_existing=True
                )
        
        reminders[user_id].append(reminder)
        
        save_reminders()
        form = "каждый день" if interval == "день" else "каждую неделю"
        bot.send_message(
            message.chat.id,
            f"✅ Повторяющееся напоминание на {first_run.strftime('%d.%m %H:%M')} (MSK) — {event} {form}",
            reply_markup=menu_keyboard
        )

        
    except Exception as e:
        logger.error(f"Ошибка в повторяющемся напоминании: {e}")
        bot.send_message(message.chat.id, "Что-то пошло не так. Попробуйте снова.", reply_markup=ReplyKeyboardMarkup())

    del temp_repeating[user_id]

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

        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = None
        text_suffix = ""
        
        # Добавляем кнопки только если нужно подтверждение
        for rem in reminders.get(user_id, []):
            if rem["job_id"] == job_id and rem.get("needs_confirmation"):
                keyboard = InlineKeyboardMarkup()
                keyboard.row(
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{job_id}"),
                    InlineKeyboardButton("🚫 Пропустить", callback_data=f"skip:{job_id}")
                )
                text_suffix = "\n\nНажмите, если выполнили:"
                break
        
        bot.send_message(
            user_id,
            f"🔔 Напоминание: {event} (в {reminder_time_msk} по МСК){text_suffix}",
            reply_markup=keyboard or ReplyKeyboardMarkup()
        )

        logger.info(f"[REMINDER] Sent to user {user_id}")
    except Exception as e:
        logger.error(f"[REMINDER ERROR] {e}")

    for rem in reminders.get(user_id, []):
        if rem["job_id"] == job_id:
            if rem.get("is_repeating"):
                return  # Повторяющееся само себе продолжит
            if rem.get("needs_confirmation"):
                # Перезапуск через repeat_interval минут
                interval = rem.get("repeat_interval", 30)
                new_job_id = str(uuid.uuid4())
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

async def repeat_reminder_check(reminder, context):
    if reminder.confirmed:
        job = scheduler.get_job(f"repeat_{reminder.id}")
        if job:
            job.remove()
        return

    await send_reminder_with_confirmation(reminder, context)

async def send_reminder_with_confirmation(reminder, context):
    keyboard = [
        [InlineKeyboardButton("☑️ Подтвердить", callback_data=f"confirm_{reminder.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=reminder.chat_id,
        text=f"🔔 Напоминание: {reminder.text}",
        reply_markup=reply_markup
    )

async def confirm_reminder(update, context):
    query = update.callback_query
    await query.answer()

    reminder_id = query.data.split('_')[1]
    for r in reminders:
        if str(r.id) == reminder_id:
            r.confirmed = True
            job = scheduler.get_job(f"repeat_{r.id}")
            if job:
                job.remove()
            save_reminders()
            await query.edit_message_text(text=f"✅ Напоминание подтверждено: {r.text}")
            break


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
        custom_interval = int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else 30

        sorted_reminders = sorted(reminders[user_id], key=lambda item: item["time"])

        for i in indices:
            if 0 < i <= len(sorted_reminders):
                rem = sorted_reminders[i - 1]
                # Переключаем: если уже был включён — отключаем
                if rem.get("needs_confirmation"):
                    rem["needs_confirmation"] = False
                    rem.pop("repeat_interval", None)
                else:
                    rem["needs_confirmation"] = True
                    rem["repeat_interval"] = custom_interval

        save_reminders()
        bot.send_message(
            message.chat.id,
            f"✅ Обновлено! Повтор через {custom_interval} мин. (если включено)",
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
        if rem["job_id"] == job_id:
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm:") or call.data.startswith("skip:"))
def handle_confirmation(call):
    user_id = call.from_user.id
    ensure_user_exists(user_id)
    action, job_id = call.data.split(":")

    for rem in reminders[user_id]:
        if rem["job_id"] == job_id:
            if action == "confirm":
                rem["needs_confirmation"] = False
                rem.pop("repeat_interval", None)
                try:
                    scheduler.remove_job(job_id)
                except:
                    pass
                save_reminders()
                bot.answer_callback_query(call.id, "✅ Подтверждено!")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                bot.send_message(user_id, f"Напоминание «{rem['text']}» отмечено как выполненное.")
            elif action == "skip":
                bot.answer_callback_query(call.id, "🔄 Напоминание останется активным.")
            return

@bot.callback_query_handler(func=lambda call: call.data.startswith("weekday_"))
def handle_weekday_selection(call):
    user_id = call.from_user.id
    selected = selected_weekdays.get(user_id, [])
    day_index = int(call.data.split("_")[1])

    if day_index in selected:
        selected.remove(day_index)
    else:
        selected.append(day_index)

    selected_weekdays[user_id] = selected
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=create_weekday_keyboard(user_id)
    )

@bot.callback_query_handler(func=lambda call: call.data == "weekday_done")
def handle_weekday_done(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    selected = selected_weekdays.get(user_id, [])
    temp = temp_repeating.get(user_id)

    if not selected or not temp:
        bot.answer_callback_query(call.id, "Выберите хотя бы один день.")
        return

    try:
        hour, minute = map(int, temp["time_str"].split("."))
        moscow = timezone('Europe/Moscow')
        now = datetime.now(moscow)
        event = temp["event"]
        day_names = [DAYS_RU[i].lower()[:2] for i in selected]
        day_str = ", ".join(day_names)

        ensure_user_exists(user_id)
        created_times = []

        for weekday in selected:
            # вычисляем ближайшую дату выбранного дня недели
            days_ahead = (weekday - now.weekday() + 7) % 7
            target_date = now + timedelta(days=days_ahead)
            reminder_time = moscow.localize(datetime.combine(target_date.date(), datetime.strptime(temp["time_str"], "%H.%M").time()))
            reminder_utc = reminder_time.astimezone(utc)
            job_id = str(uuid.uuid4())

            scheduler.add_job(send_reminder, 'interval', weeks=1, start_date=reminder_utc,
                              args=[user_id, event, temp["time_str"], job_id], id=job_id)

            reminders[user_id].append({
                "time": reminder_utc,
                "text": f"{event} (повт. неделя {DAYS_RU[weekday].lower()[:2]})",
                "job_id": job_id,
                "is_repeating": True,
                "needs_confirmation": False
            })
            created_times.append(reminder_time.strftime('%a %H:%M'))

        save_reminders()

        bot.edit_message_text(
            f"✅ Напоминание «{event}» будет повторяться каждую неделю в: {', '.join(created_times)}",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=None
        )
        bot.send_message(chat_id, "Главное меню:", reply_markup=menu_keyboard)

        del selected_weekdays[user_id]
        del temp_repeating[user_id]

    except Exception as e:
        logger.error(f"Ошибка в handle_weekday_done: {e}")
        bot.send_message(chat_id, "Ошибка при создании напоминания. Попробуйте снова.", reply_markup=menu_keyboard)
    
if __name__ == "__main__":
    load_reminders()
    restore_jobs()

    ping_thread = threading.Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()
    app.run(host="0.0.0.0", port=10000)
