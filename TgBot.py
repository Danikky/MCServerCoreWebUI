import telebot
import stmc
from main import server
# Конфигурация (ЗАМЕНИТЕ НА СВОИ ДАННЫЕ)
BOT_TOKEN = "7911812987:AAHpm_K4N2DKRBKkDaNOCMkXCcY1MIINwgc"
CHAT_ID = "855423845"  # Ваш ID в Telegram
# --------------------------------------

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start']) 
def send_welcome(message): 
    bot.reply_to(message, """
Для получения списка команд введите /help .
""")

# /help
@bot.message_handler(commands=['help']) 
def send_welcome(message): 
    bot.reply_to(message, """
Список команд:
> /auth (не работает) # авторизация в системе
> /start_server 
> /stop_server 
> /kill_server (не работает)
> /restart_server (не работает)
> /online
> /system_monitor 
> /command <команда> (не работает)
""")

# /online
@bot.message_handler(commands=['online']) 
def send_online(message):
    if server.is_server_running():
        online = stmc.get_online()
        for i in range(len(online)):
            online[i] = online + "\n"
        bot.reply_to(message, f"""Список игроков:
{online}
""")
    else:
        bot.reply_to(message, f"Сервер выключен")

# /system_monitoring
@bot.message_handler(commands=['system_monitor'])
def send_system(message):
    if server.is_server_running():
        system = server.system_monitoring() # обновляет данные 
        bot.reply_to(message, f"""
CPU : {system["cpu_percent"]}
RAM : {system["ram_used"]} / {system["ram_total"]} | {system["ram_percent"]}
DISK : {system["disk_used"]} / {system["disk_total"]} | {system["disk_percent"]} (Free: {system["disk_free"]})
""")
    else:
        bot.reply_to(message, f"Сервер выключен")
    
# /command
@bot.message_handler(commands=['command'])
def send_system(message):
    if server.is_server_running():
        response = server.send_rcon_command(message.text)
        bot.reply_to(message, f"Ответ сервера: {response}")
    else:
        bot.reply_to(message, f"Сервер выключен")

# /start_server
@bot.message_handler(commands=['command'])
def send_system(message):
    if server.is_server_running():
        bot.reply_to(message, "Сервер уже запущен")
    else:
        server.start_server()
        bot.reply_to(message, f"Попытка запуска сервера...")

# /stop_server
@bot.message_handler(commands=['command'])
def send_system(message):
    if server.is_server_running():
        response = server.send_rcon_command("stop")
        bot.reply_to(message, f"Ответ сервера: {response}")
    else:
        bot.reply_to(message, f"Сервер уже выключен")


# работа бота
if __name__ == "__main__":
    bot.polling()
