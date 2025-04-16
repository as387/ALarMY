import telebot
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import re
from telebot import types
import logging
import uuid
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Замените на ваш токен
bot = telebot.TeleBot(BOT_TOKEN)

scheduler = BackgroundScheduler()
reminders = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)


def main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Добавить напоминание"))
    keyboard.add(types.KeyboardButton("Показать напоминания"))
    return keyboard


def ensure_user_exists(user_id):
    if user_id not in reminders:
        reminders[user_id] = []


@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    bot.send_message(message.chat.id, "ЙОУ! Выберите действие:\n п.с. бот иногда засыпает потому иногда надо пару раз нажать на кнопки чтобы он проснулся:)", reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda message: message.text == "Добавить напоминание")
def add_reminder(message):
    bot.send_message(message.chat.id, "Введите напоминание в формате ЧЧ.ММ *событие*.\n (через точку молю)", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_reminder)


def process_reminder(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    pattern = r'^\d{1,2}\.\d{2} .+$'
    if re.match(pattern, message.text):
        try:
            time_str, event = message.text.split(' ', 1)
            time_obj = datetime.strptime(time_str, "%H.%M").time()
            now = datetime.now()
            reminder_datetime = datetime.combine(now.date(), time_obj)
            if reminder_datetime < now:
                reminder_datetime = datetime.combine(now.date(), time_obj) + timedelta(days=1)

            job_id = str(uuid.uuid4())
            reminders[user_id].append((reminder_datetime, event, job_id))
            scheduler.add_job(
                send_reminder,
                trigger='date',
                run_date=reminder_datetime,
                args=[user_id, event, bot, reminder_datetime.strftime("%H:%M"), job_id],
                id=job_id
            )
            bot.send_message(message.chat.id, f"Напоминание установлено на {reminder_datetime.strftime('%d.%m %H:%M')} - {event}", reply_markup=main_menu_keyboard())
        except ValueError:
            bot.send_message(message.chat.id, "Неверный формат времени. Попробуйте снова.", reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(message, process_reminder)
    else:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(message, process_reminder)


@bot.message_handler(func=lambda message: message.text == "Показать напоминания")
def show_reminders(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    if not reminders[user_id]:
        bot.send_message(message.chat.id, "У вас нет активных напоминаний.", reply_markup=main_menu_keyboard())
        return

    sorted_reminders = sorted(reminders[user_id], key=lambda item: item[0])
    text = "Ваши напоминания:\n"
    for i, (time, reminder_text, job_id) in enumerate(sorted_reminders, start=1):
        text += f"{i}. {time.strftime('%d.%m %H:%M')} - {reminder_text}\n"
    text += "\nВведите номера напоминаний для удаления (через пробел):"
    bot.send_message(message.chat.id, text, reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_remove_input)


def process_remove_input(message):
    user_id = message.from_user.id
    ensure_user_exists(user_id)
    try:
        reminder_indices = list(map(int, re.findall(r'\d+', message.text)))
        reminders_to_remove = []
        sorted_reminders = sorted(reminders[user_id], key=lambda item: item[0])

        for reminder_index in reminder_indices:
            if 0 < reminder_index <= len(sorted_reminders):
                time, reminder_text, job_id = sorted_reminders[reminder_index - 1]
                for job in scheduler.get_jobs():
                    if job.id == job_id:
                        job.remove()
                        break
                reminders_to_remove.append((reminder_index, time, reminder_text))
        
        text = ""
        if reminders_to_remove:
            for index, time, reminder_text in sorted(reminders_to_remove, reverse=True):
                for i, (time2, reminder_text2, job_id) in enumerate(reminders[user_id]):
                    if time == time2 and reminder_text == reminder_text2:
                        reminders[user_id].pop(i)
                        break
        
        if reminders[user_id]:
            sorted_reminders = sorted(reminders[user_id], key=lambda item: item[0])
            text = "Ваши напоминания:\n"
            for i, (time, reminder_text, job_id) in enumerate(sorted_reminders, start=1):
                 text += f"{i}. {time.strftime('%d.%m %H:%M')} - {reminder_text}\n"
            text += "_____________________________________\n"
        if reminders_to_remove:
           text += "".join(f"удалено - {reminder_text} {time.strftime('%H:%M')}\n" for index, time, reminder_text in reminders_to_remove)
            
        if not reminders[user_id] and not reminders_to_remove:
             text = "У вас нет активных напоминаний.\n"
        bot.send_message(message.chat.id, text, reply_markup=main_menu_keyboard())
    except ValueError:
         bot.send_message(message.chat.id, "Некорректный ввод, отмена удаления.", reply_markup=main_menu_keyboard())
    bot.register_next_step_handler(message, start_command)


def send_reminder(user_id, event, bot, time, job_id):
    logger.info(f"send_reminder STARTED: user_id={user_id}, reminder_text={event}, time={time}")
    bot.send_message(user_id, f"Напоминание: {event}", reply_markup=main_menu_keyboard())
    if user_id in reminders:
        reminders[user_id] = [rem for rem in reminders[user_id] if rem[2] != job_id]
    logger.info(f"send_reminder: сообщение отправлено")


if __name__ == '__main__':
    scheduler.start()
    bot.polling(none_stop=True)
