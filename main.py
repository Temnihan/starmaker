import re
import requests
import telebot
from pydub import AudioSegment
import io

# ===== 1. Токен бота (получи у @BotFather) =====
TOKEN = "8665718973:AAEw3or2gqDbfJc17Xo7O7mKfDqaXHzKfoc"
bot = telebot.TeleBot(TOKEN)

# ===== 2. Функция, которая вытаскивает recordingId из текста =====
def extract_recording_id(text):
    """
    Ищет в тексте что-то похожее на recordingId=число
    и возвращает это число в виде строки, или None, если не найдено.
    """
    # Регулярное выражение: ищем recordingId= и захватываем цифры после =
    match = re.search(r'recordingId=(\d+)', text)
    if match:
        return match.group(1)  # первая захваченная группа – это число
    else:
        return None

# ===== 3. Функция скачивания файла по ссылке =====
def download_video(url):
    """
    Скачивает файл по ссылке и возвращает его содержимое (байты).
    Если ошибка – возвращает None.
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.content  # байты видео
        else:
            return None
    except Exception as e:
        print("Ошибка при скачивании:", e)
        return None

# ===== 4. Обработчик всех текстовых сообщений =====
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    if not text:
        bot.reply_to(message, "Пришли текст с ссылкой")
        return

    # Пытаемся найти recordingId
    rec_id = extract_recording_id(text)
    if not rec_id:
        bot.reply_to(message, " Проверь ссылку.")
        return

    # Формируем ссылку для скачивания
    video_url = f"https://static.smoutro.com/production/uploading/recordings/{rec_id}/master.mp4"
    bot.reply_to(message, f"Нашёл ID: {rec_id}. Скачиваю видео...")

    # Скачиваем видео
    video_data = download_video(video_url)
    if video_data is None:
        bot.reply_to(message, "Не удалось скачать видео по ссылке. Возможно, файл не существует.")
        return

    # Отправляем видео пользователю (как документ или как видео)
    try:
        # Можно отправить как видеофайл (telegram поддерживает mp4)
        bot.send_video(message.chat.id, video_data, caption="Вот твоё видео!")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при отправке видео: {e}")

# ===== 5. Запуск бота =====
if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True)

