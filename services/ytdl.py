"""
Сервис для получения информации и скачивания через yt-dlp.
Требуется FFmpeg в системе для объединения потоков и извлечения аудио.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yt_dlp


class YTDLServiceError(Exception):
    """Ошибка при работе с yt-dlp."""
    pass


def _get_ydl_opts_base() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
    }
    # Прокси для доступа к YouTube из регионов с блокировкой (например РФ)
    proxy = os.getenv("YTDL_PROXY", "").strip() or None
    if proxy:
        opts["proxy"] = proxy

        # Добавляем cookies, если файл существует
    cookies_path = Path(__file__).parent.parent / "cookies.txt"
    if cookies_path.exists():
        opts["cookiefile"] = str(cookies_path)

    return opts


def extract_info(url: str, *, in_playlist: bool = True) -> dict[str, Any]:
    """
    Получить информацию о видео или первом видео в плейлисте.
    Для плейлиста возвращаем информацию о первом ролике (можно расширить до списка).
    """
    opts = {**_get_ydl_opts_base()}
    if in_playlist:
        opts["extract_flat"] = "in_playlist"
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False, process=True)
        except yt_dlp.utils.DownloadError as e:
            raise YTDLServiceError(_human_error(str(e)))
        except Exception as e:
            raise YTDLServiceError(f"Ошибка получения данных: {e!s}")

    if not info:
        raise YTDLServiceError("Не удалось получить информацию по ссылке.")

    # Если это плейлист — берём первое видео для выбора форматов
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise YTDLServiceError("Плейлист пуст или недоступен.")
        first = entries[0]
        if first is None:
            raise YTDLServiceError("Первое видео плейлиста недоступно.")
        # id может быть в first, или это уже полный info одного видео
        if first.get("_type") == "playlist":
            raise YTDLServiceError("Вложенные плейлисты не поддерживаются.")
        url = first.get("url") or first.get("webpage_url") or url
        if not url and first.get("id"):
            url = f"https://www.youtube.com/watch?v={first['id']}"
        if url:
            return extract_info(url, in_playlist=False)
        info = first

    return info


def get_video_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Доступные видеоформаты (с видео или комбинированные)."""
    formats = info.get("formats") or []
    # Оставляем форматы с видео, сортируем по разрешению
    video_formats = []
    seen = set()
    for f in formats:
        if f.get("vcodec") == "none":
            continue
        height = f.get("height") or 0
        ext = (f.get("ext") or "mp4").lower()
        key = (height, ext)
        if key in seen:
            continue
        seen.add(key)
        label = f"{height}p" if height else (f.get("format_note") or ext)
        video_formats.append({
            "format_id": f.get("format_id"),
            "height": height,
            "ext": ext,
            "label": str(label),
            "filesize": f.get("filesize"),
        })
    video_formats.sort(key=lambda x: (-(x["height"] or 0), x["ext"]))
    # Ограничиваем список разумным числом вариантов
    return video_formats[:15]


def get_audio_formats() -> list[dict[str, Any]]:
    """Варианты качества аудио (битрейт через postprocessor)."""
    return [
        {"format_id": "audio_320", "label": "320 kbps (MP3)", "codec": "mp3"},
        {"format_id": "audio_256", "label": "256 kbps (M4A)", "codec": "m4a"},
        {"format_id": "audio_128", "label": "128 kbps (MP3)", "codec": "mp3"},
    ]


def _human_error(err: str) -> str:
    """Упростить сообщение об ошибке для пользователя."""
    if "Private video" in err or "private" in err.lower():
        return "Видео приватное и недоступно для скачивания."
    if "removed" in err.lower() or "unavailable" in err.lower():
        return "Видео удалено или недоступно."
    if "blocked" in err.lower() or "copyright" in err.lower():
        return "Доступ к видео ограничен (блокировка или авторские права)."
    if "geo" in err.lower() or "country" in err.lower():
        return "Видео недоступно в вашем регионе."
    if "Sign in" in err or "login" in err.lower():
        return "Требуется авторизация на YouTube (такие видео бот не поддерживает)."
    if "Unable to extract" in err or "No video formats" in err:
        return "YouTube изменил страницу или формат — попробуйте позже или другую ссылку."
    return err[:400]


def download_video(
    url: str,
    out_dir: Path,
    format_id: str | None = None,
    height: int | None = None,
) -> tuple[Path, str]:
    """
    Скачать видео в out_dir. Возвращает (путь к файлу, заголовок).
    Приоритет: если передан format_id – используем его.
    Если нет, но передан height – выбираем лучший формат с этим разрешением.
    Если нет ни того, ни другого – выбираем лучшее качество с mp4 контейнером.
    """
    out_tpl = str(out_dir / "%(title).100s.%(ext)s")

    # Формируем строку формата для yt-dlp
    if format_id:
        format_spec = format_id + "+bestaudio/best"
    elif height:
        # Ищем видео с нужным разрешением, предпочитая mp4, и добавляем лучшее аудио
        format_spec = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    else:
        format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    opts = {
        **_get_ydl_opts_base(),
        "outtmpl": out_tpl,
        "format": format_spec,
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            # Если произошла ошибка "format not available" – пробуем fallback
            if "format not available" in str(e).lower():
                # Пробуем скачать в лучшем качестве без указания конкретного формата
                opts["format"] = "bestvideo+bestaudio/best"
                try:
                    info = ydl.extract_info(url, download=True)
                except Exception as e2:
                    raise YTDLServiceError(_human_error(str(e2)))
            else:
                raise YTDLServiceError(_human_error(str(e)))
        except Exception as e:
            raise YTDLServiceError(f"Ошибка загрузки: {e!s}")

    path = ydl.prepare_filename(info)
    if not Path(path).exists():
        raise YTDLServiceError("Файл не был создан после загрузки.")
    title = info.get("title") or "video"
    return Path(path), title


def download_audio(
    url: str,
    out_dir: Path,
    format_id: str = "audio_128",
) -> tuple[Path, str]:
    """
    Скачать только аудио. format_id: audio_320, audio_256, audio_128.
    """
    codec = "mp3" if "mp3" in format_id or format_id == "audio_320" or format_id == "audio_128" else "m4a"
    out_tpl = str(out_dir / "%(title).100s.%(ext)s")
    # Битрейт задаётся через postprocessor
    opts = {
        **_get_ydl_opts_base(),
        "outtmpl": out_tpl,
        "format": "bestaudio/best",
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "320" if "320" in format_id else "256" if "256" in format_id else "128"},
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise YTDLServiceError(_human_error(str(e)))
        except Exception as e:
            raise YTDLServiceError(f"Ошибка загрузки аудио: {e!s}")

    path = Path(ydl.prepare_filename(info))
    # FFmpeg меняет расширение на codec
    for ext in (f".{codec}", ".mp3", ".m4a"):
        p = path.with_suffix(ext)
        if p.exists():
            return p, info.get("title") or "audio"
    if path.exists():
        return path, info.get("title") or "audio"
    raise YTDLServiceError("Аудиофайл не был создан.")


def extract_playlist_info(url: str) -> list[dict[str, Any]]:
    """
    Получить информацию о всех видео в плейлисте.
    Возвращает список словарей: [{'url': str, 'title': str, 'id': str, 'duration': int}, ...]
    """
    opts = {
        **_get_ydl_opts_base(),
        "extract_flat": "in_playlist",  # не скачиваем, только метаданные
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise YTDLServiceError(_human_error(str(e)))
        except Exception as e:
            raise YTDLServiceError(f"Ошибка получения плейлиста: {e!s}")

    if not info or info.get('_type') != 'playlist':
        raise YTDLServiceError("Ссылка не является плейлистом или не удалось распознать.")

    entries = info.get('entries') or []
    if not entries:
        raise YTDLServiceError("Плейлист пуст.")

    result = []
    for entry in entries:
        if not entry:
            continue
        video_url = entry.get('url') or entry.get('webpage_url')
        if not video_url and entry.get('id'):
            video_url = f"https://www.youtube.com/watch?v={entry['id']}"
        result.append({
            'url': video_url,
            'title': entry.get('title', 'Без названия'),
            'id': entry.get('id'),
            'duration': entry.get('duration', 0),
        })
    return result


def check_ffmpeg() -> bool:
    """Проверить, установлен ли FFmpeg (нужен для объединения и аудио)."""
    try:
        subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            timeout=5,
        )
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
