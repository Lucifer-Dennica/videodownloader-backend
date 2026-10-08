# VideoDownloader Backend

Сервер для Android-приложения VideoDownloader.

## Что делает

- TikTok — через tikwm (без блокировок)
- Rutube, SoundCloud, Reddit, Pinterest, YouTube, VK и др. — через yt-dlp

## Эндпоинты

- GET `/api/health` — проверка статуса
- POST `/api/resolve` — получить прямую ссылку на видео

### Пример запроса

```json
POST /api/resolve
{
  "url": "https://vt.tiktok.com/ZSb65dfvA/",
  "audio_only": false,
  "quality": "max"
}
