import telebot
import stmc

# Конфигурация (ЗАМЕНИТЕ НА СВОИ ДАННЫЕ)
BOT_TOKEN = "7911812987:AAHpm_K4N2DKRBKkDaNOCMkXCcY1MIINwgc"
CHAT_ID = "855423845"  # Ваш ID в Telegram
# --------------------------------------

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start']) 
def send_welcome(message): 
    bot.reply_to(message, """
Список команд:
> /start_server (не работает)
> /stop_server (не работает)
> /kill_server (не работает)
> /restart_server (не работает)
> /online 
> / ...
""")

# /online
@bot.message_handler(commands=['online']) 
def send_online(message):
    online = stmc.get_online()
    for i in range(len(online)):
        online[i] = online + "\n"
    bot.reply_to(message, f"""Список игроков:
{online}
""")

if __name__ == "__main__":
    bot.polling()
