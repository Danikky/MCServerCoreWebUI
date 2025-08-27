import telebot
import stmc
from openai import OpenAI
from main import server

BOT_TOKEN = "7911812987:AAHpm_K4N2DKRBKkDaNOCMkXCcY1MIINwgc"
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="local-model")

bot = telebot.TeleBot(BOT_TOKEN)
print("Всё запущено и работает!")

@bot.message_handler(content_types=["text"]) 
def send_to_ai(message):
    from main import server
    bot.send_chat_action(message.chat.id, "typing")
    msg = message.text
    print("User: ", msg)
    system = server.system_monitoring()
    players_data = server.update_players_data()
    server_info = f"""Ты - ИИ, который должен помогать пользователю управлять minecraft сервером.
Ты подключен к системе которая предоставляет тебе актуальную информацию о сервере. Ты пока сам никак не можешь взаимодействовать с сервером. Отвечай на вопросы пользователя, опирайся только на предоставленные данные, не выдумывай и не обманывай. Если ты в чём то не уверен, то говори что не уверен. Отвечай кратко, не пиши 'заключение', 'рекомендации', 'итог' и т. д.
Отвечай только на вопрос пользователя, не говори нечего лишнего. Не используй никаких текстовых *эффектов*, они не работают в чате телеграмма.
Примечание: ты работаешь на запущенном сервере в LM studio, а общение с тобой происходит через телеграмм бота.
Информация о сервере:
- Состояние сервера: {server.is_server_running()}
- Ядро сервера: {server.core}
- Онлайн: {len(server.online)} / {server.get_properties_value("max-players")}
- Игроки на сервере: {server.online}
- Список забаненых: {players_data["banlist"]}
- Список операторов сервера: {players_data["oplist"]}
- CPU: {system["cpu_percent"]} | ядра: {system["cpu_cores"]}
- RAM: {system["ram_used"]} / {system["ram_total"]} | {system["ram_percent"]}
- disk: {system["disk_used"]} / {system["disk_total"]} | {system["disk_percent"]}
"""
    msg = [
        {
            "role": "system", 
            "content": server_info
        },
        {
            "role": "user", 
            "content": msg
        }
    ]
    model = "local-model"
    try:
        bot.send_chat_action(message.chat.id, "typing")
        stream = client.chat.completions.create(
            model=model,
            messages=msg,
            temperature=0.7,
            stream=True
        )
        full_response = ""
        print("Ответ AI: ", end="", flush=True)
        for chunk in stream:
            if chunk.choices[0].delta.content:
                piece = chunk.choices[0].delta.content
                print(piece, end="", flush=True)
                full_response += piece
        print("\n")
    except Exception as e:
        print(f"Ошибка AI: {e}")
    finally:
        bot.reply_to(message, full_response)

# работа бота
if __name__ == "__main__":
    bot.polling()
