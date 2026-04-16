# Используем официальный образ Python как основу
FROM python:3.10-slim

# Устанавливаем FFmpeg из системного репозитория
# apt-get -y update обновляет список пакетов
# && apt-get -y install ffmpeg устанавливает FFmpeg
# && apt-get clean очищает кэш, чтобы уменьшить размер итогового образа
RUN apt-get -y update && apt-get -y install ffmpeg && apt-get clean

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл со списком зависимостей
COPY requirements.txt .

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код бота в рабочую директорию
COPY . .

# Задаем команду для запуска бота
CMD ["python", "./main.py"]