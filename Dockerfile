FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Запускаем POT-провайдер в фоне и сам сервер
CMD ["sh", "-c", "python -m bgutil_ytdlp_pot_provider & uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
