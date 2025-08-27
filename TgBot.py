import telebot
import stmc
import sqlite3
from main import server
from openai import OpenAI

BOT_TOKEN = "7911812987:AAHpm_K4N2DKRBKkDaNOCMkXCcY1MIINwgc"
CHAT_ID = "855423845"  # Мой ID в Telegram
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="google/gemma-3-27b")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(type="text") 
def send_to_ai(message):
    msg = message.text
    system = server.system_monitoring()
    players_data = server.update_players_data()
    system_info = f"""Информация о сервере:
Состояние сервера: {server.is_server_running()}
Ядро сервера: {server.core}
настройки сервера: {server.get_properties_data()}
Онлайн: {len(server.online)} / {server.get_properties_value("max-players")}
Игроки на сервере: {server.online}
Список забаненых: {players_data["banlist"]}
Список операторов сервера: {players_data["oplist"]}
CPU: {system["cpu_percent"]} | ядра: {system["cpu_cores"]}
RAM: {system["ram_used"]} / {system["ram_total"]} | {system["ram_percent"]}
disk: {system["disk_used"]} / {system["disk_total"]} | {system["disk_percent"]}
"""     
    msg = [
        {
            "role": "system", 
            "content": system_info
        },
        {
            "role": "user", 
            "content": msg
        }
    ]
    model = "local-model"
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=msg,
            temperature=0.7,
            stream=True
        )
        full_response = ""
        print("", end="", flush=True)
        for chunk in stream:
            if chunk.choices[0].delta.content:
                piece = chunk.choices[0].delta.content
                print(piece, end="", flush=True)
                full_response += piece
        print("\n")
    except Exception as e:
        stmc.add_line(f"Ошибка AI: {e}")
        print(f"Ошибка AI: {e}")
    finally:
        bot.reply_to(full_response, "")

# работа бота
if __name__ == "__main__":
    bot.polling()
