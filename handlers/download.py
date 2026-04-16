import asyncio
import re
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import DOWNLOADS_DIR, MAX_FILE_SIZE, UPLOAD_TIMEOUT
from keyboards import (
    audio_quality_kb,
    back_to_menu_kb,
    playlist_action_kb,
    type_choice_kb,
    video_quality_kb,
)
from services.ytdl import (
    YTDLServiceError,
    extract_info,
    extract_playlist_info,
    get_audio_formats,
    get_video_formats,
    download_video,
    download_audio,
)
from states import DownloadStates

router = Router()

URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/playlist\?list=)[\w\-]+",
    re.IGNORECASE,
)


async def _delete_status(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _delete_bot_messages(bot: Bot, chat_id: int, *message_ids: int | None) -> None:
    for mid in message_ids:
        await _delete_status(bot, chat_id, mid)


async def _send_status(
    bot: Bot, chat_id: int, text: str, data: dict, key: str = "last_status_msg_id"
) -> Message:
    prev_id = data.get(key)
    await _delete_status(bot, chat_id, prev_id)
    msg = await bot.send_message(chat_id=chat_id, text=text)
    data[key] = msg.message_id
    return msg


# ----- Ввод ссылки -----
@router.message(DownloadStates.waiting_link, F.text)
async def on_link_sent(message: Message, bot: Bot, state: FSMContext) -> None:
    text = (message.text or "").strip()
    url = URL_PATTERN.search(text)
    if not url:
        await message.answer(
            "Это не похоже на ссылку YouTube. Отправь ссылку на видео или плейлист.",
            reply_markup=back_to_menu_kb(),
        )
        return

    url_str = url.group(0)
    data = await state.get_data()
    chat_id = message.chat.id

    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    status_msg = await _send_status(bot, chat_id, "🔍 Ищу информацию…", data)
    await state.update_data(last_status_msg_id=status_msg.message_id)

    try:
        # Проверяем, является ли ссылка плейлистом
        playlist_info = None
        is_playlist = False
        try:
            playlist_info = await asyncio.to_thread(extract_playlist_info, url_str)
            is_playlist = True
        except YTDLServiceError:
            # Не плейлист — пробуем как обычное видео
            pass

        if is_playlist:
            # Сохраняем информацию о плейлисте
            await state.update_data(
                url=url_str,
                playlist=playlist_info,
                playlist_count=len(playlist_info),
                last_status_msg_id=status_msg.message_id,
            )
            await _delete_status(bot, chat_id, status_msg.message_id)
            await state.update_data(last_status_msg_id=None)

            # Предлагаем выбор действия
            await message.answer(
                f"📀 Найден плейлист из **{len(playlist_info)}** видео.\n\n"
                f"Telegram не позволяет отправлять больше 50 МБ за раз, но я могу скачать все видео **локально** на твой сервер (в папку `{DOWNLOADS_DIR}`).\n\n"
                f"Выбери действие:",
                reply_markup=playlist_action_kb(),
            )
            await state.set_state(DownloadStates.chose_playlist_action)
            return

        # --- Обычное видео ---
        info = await asyncio.to_thread(extract_info, url_str)
    except YTDLServiceError as e:
        await _delete_status(bot, chat_id, status_msg.message_id)
        await state.update_data(last_status_msg_id=None)
        await message.answer(
            f"❌ Ошибка: {e!s}",
            reply_markup=back_to_menu_kb(),
        )
        return

    # Обработка одиночного видео (как было)
    title = info.get("title") or "Без названия"
    video_formats = get_video_formats(info)
    await state.update_data(
        url=url_str,
        title=title,
        video_formats=video_formats,
        last_status_msg_id=status_msg.message_id,
    )
    await state.set_state(DownloadStates.chose_type)

    await _delete_status(bot, chat_id, status_msg.message_id)
    await state.update_data(last_status_msg_id=None)

    await message.answer(
        f"📌 Найдено: {title[:200]}\n\nВыбери, что скачать:",
        reply_markup=type_choice_kb(),
    )


# ----- Обработка выбора действия с плейлистом -----
@router.callback_query(DownloadStates.chose_playlist_action, F.data == "playlist_first_only")
async def playlist_first_only(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Скачать только первое видео из плейлиста (обычный режим)"""
    await callback.answer()
    data = await state.get_data()
    playlist = data.get("playlist")
    if not playlist:
        await callback.message.edit_text("Ошибка: плейлист не найден. Начни заново.")
        await state.clear()
        return

    first_video = playlist[0]
    url = first_video['url']
    title = first_video['title']

    # Получаем информацию о форматах для первого видео
    try:
        info = await asyncio.to_thread(extract_info, url)
    except YTDLServiceError as e:
        await callback.message.edit_text(f"❌ Ошибка получения видео: {e!s}")
        await state.clear()
        return

    video_formats = get_video_formats(info)
    await state.update_data(
        url=url,
        title=title,
        video_formats=video_formats,
        playlist_mode=False,
    )
    await state.set_state(DownloadStates.chose_type)
    await callback.message.edit_text(
        f"📌 Первое видео из плейлиста: {title[:200]}\n\nВыбери, что скачать:",
        reply_markup=type_choice_kb(),
    )


@router.callback_query(DownloadStates.chose_playlist_action, F.data == "playlist_full_local")
async def playlist_full_local(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Скачать весь плейлист локально (без отправки в Telegram)"""
    await callback.answer()
    data = await state.get_data()
    playlist = data.get("playlist")
    if not playlist:
        await callback.message.edit_text("Ошибка: плейлист не найден. Начни заново.")
        await state.clear()
        return

    count = len(playlist)
    if count > 100:
        await callback.message.edit_text(
            f"⚠️ В плейлисте {count} видео. Это очень много, скачивание может занять часы.\n"
            "Продолжить? (бот может работать медленно, но не зависнет)",
            reply_markup=playlist_action_kb(confirm=True)  # нужна новая клавиатура с Да/Нет
        )
        await state.update_data(playlist_confirm_needed=True)
        return

    # Переходим к выбору типа (видео/аудио) для всего плейлиста
    await state.update_data(playlist_full=True, playlist_index=0, playlist_results=[])
    await state.set_state(DownloadStates.chose_type)
    await callback.message.edit_text(
        f"🎬 Плейлист из **{count}** видео.\n\n"
        "Выбери, что скачивать из каждого видео (видео или аудио), и качество.\n"
        "Все файлы сохранятся в папку на сервере.\n\n"
        "Выбери тип:",
        reply_markup=type_choice_kb(),
    )


@router.callback_query(DownloadStates.chose_playlist_action, F.data.startswith("playlist_confirm_"))
async def playlist_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение для больших плейлистов"""
    await callback.answer()
    choice = callback.data.split("_")[-1]  # 'yes' или 'no'
    if choice == "yes":
        data = await state.get_data()
        await state.update_data(playlist_full=True, playlist_index=0, playlist_results=[])
        await state.set_state(DownloadStates.chose_type)
        await callback.message.edit_text(
            "Начинаем подготовку к скачиванию. Выбери тип (видео/аудио):",
            reply_markup=type_choice_kb(),
        )
    else:
        await callback.message.edit_text("Отменено.", reply_markup=back_to_menu_kb())
        await state.clear()


# ----- Выбор типа для плейлиста или одиночного видео -----
@router.callback_query(DownloadStates.chose_type, F.data == "type_video")
async def on_type_video(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    playlist_full = data.get("playlist_full", False)

    if playlist_full:
        # Для плейлиста: сохраняем тип и переходим к выбору качества
        await state.update_data(media_type="video")
        await state.set_state(DownloadStates.chose_quality)
        # Получаем форматы из первого видео (они будут одинаковы для всех)
        playlist = data.get("playlist")
        if playlist:
            try:
                info = await asyncio.to_thread(extract_info, playlist[0]['url'])
                formats = get_video_formats(info)
                await callback.message.edit_text(
                    "Выбери качество видео для ВСЕХ видео в плейлисте:",
                    reply_markup=video_quality_kb(formats),
                )
            except Exception as e:
                await callback.message.edit_text(f"Ошибка получения форматов: {e}")
                await state.clear()
        else:
            await callback.message.edit_text("Ошибка: плейлист не найден.")
            await state.clear()
    else:
        # Одиночное видео
        formats = data.get("video_formats") or []
        if not formats:
            await callback.message.edit_text(
                "Не удалось получить список форматов. Попробуй аудио или другую ссылку.",
                reply_markup=type_choice_kb(),
            )
            return
        await state.set_state(DownloadStates.chose_quality)
        await state.update_data(media_type="video")
        await callback.message.edit_text(
            "Выбери качество видео:",
            reply_markup=video_quality_kb(formats),
        )


@router.callback_query(DownloadStates.chose_type, F.data == "type_audio")
async def on_type_audio(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    playlist_full = data.get("playlist_full", False)

    await state.update_data(media_type="audio")
    await state.set_state(DownloadStates.chose_quality)
    audio_formats = get_audio_formats()
    if playlist_full:
        await callback.message.edit_text(
            "Выбери качество аудио для ВСЕХ видео в плейлисте:",
            reply_markup=audio_quality_kb(audio_formats),
        )
    else:
        await callback.message.edit_text(
            "Выбери качество аудио:",
            reply_markup=audio_quality_kb(audio_formats),
        )


@router.callback_query(DownloadStates.chose_quality, F.data == "quality_back")
async def quality_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    playlist_full = data.get("playlist_full", False)
    if playlist_full:
        # Возврат к выбору типа для плейлиста
        await state.set_state(DownloadStates.chose_type)
        await callback.message.edit_text(
            "Выбери тип (видео/аудио):",
            reply_markup=type_choice_kb(),
        )
    else:
        await state.set_state(DownloadStates.chose_type)
        await callback.message.edit_text(
            "Выбери, что скачать:",
            reply_markup=type_choice_kb(),
        )


# ----- Выбор качества и запуск загрузки -----
@router.callback_query(DownloadStates.chose_quality, F.data.startswith("quality_v_"))
async def on_quality_video(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    format_id = callback.data.replace("quality_v_", "", 1)
    if not format_id:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    await _run_download(callback, bot, state, media_type="video", format_id=format_id)


@router.callback_query(DownloadStates.chose_quality, F.data.startswith("quality_a_"))
async def on_quality_audio(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    format_id = callback.data.replace("quality_a_", "", 1)
    if not format_id:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    await _run_download(callback, bot, state, media_type="audio", format_id=format_id)


async def _run_download(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    *,
    media_type: str,
    format_id: str,
) -> None:
    await callback.answer()
    data = await state.get_data()
    playlist_full = data.get("playlist_full", False)

    if playlist_full:
        # --- Скачивание всего плейлиста локально ---
        await _download_playlist(callback, bot, state, media_type, format_id)
    else:
        # --- Одиночное видео (существующая логика) ---
        await _download_single(callback, bot, state, media_type, format_id)


async def _download_single(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    media_type: str,
    format_id: str,
) -> None:
    """Скачать одно видео и отправить в Telegram (старая логика)"""
    data = await state.get_data()
    url = data.get("url")
    if not url:
        await callback.message.edit_text("Сессия устарела. Начни заново.", reply_markup=back_to_menu_kb())
        await state.clear()
        return

    chat_id = callback.message.chat.id
    await state.set_state(DownloadStates.downloading)

    status_msg = await _send_status(bot, chat_id, "⬇️ Скачиваю… Подожди.", data)
    await state.update_data(last_status_msg_id=status_msg.message_id)

    try:
        if media_type == "video":
            file_path, title = await asyncio.to_thread(
                download_video, url, DOWNLOADS_DIR, format_id=format_id
            )
        else:
            file_path, title = await asyncio.to_thread(
                download_audio, url, DOWNLOADS_DIR, format_id=format_id
            )
    except YTDLServiceError as e:
        data = await state.get_data()
        await _delete_status(bot, chat_id, status_msg.message_id)
        await _delete_bot_messages(bot, chat_id, data.get("menu_message_id"), callback.message.message_id)
        await state.clear()
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ошибка загрузки: {e!s}",
            reply_markup=back_to_menu_kb(),
        )
        return
    except Exception as e:
        data = await state.get_data()
        await _delete_status(bot, chat_id, status_msg.message_id)
        await _delete_bot_messages(bot, chat_id, data.get("menu_message_id"), callback.message.message_id)
        await state.clear()
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Неожиданная ошибка: {e!s}",
            reply_markup=back_to_menu_kb(),
        )
        return

    data = await state.get_data()
    menu_msg_id = data.get("menu_message_id")
    choice_msg_id = callback.message.message_id
    await _delete_status(bot, chat_id, status_msg.message_id)
    await _delete_bot_messages(bot, chat_id, menu_msg_id, choice_msg_id)
    await state.update_data(last_status_msg_id=None)
    await state.clear()

    file_size = file_path.stat().st_size
    caption = f"📎 {title}\n🔗 Источник: {url}"
    back_kb = back_to_menu_kb()
    timeout = UPLOAD_TIMEOUT

    try:
        if file_size > MAX_FILE_SIZE:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ Файл слишком большой для отправки в Telegram ({file_size / (1024*1024):.1f} МБ). "
                    f"Лимит бота — 50 МБ.\n\n"
                    f"📎 {title}\n🔗 Скачай по ссылке на источник: {url}"
                ),
                reply_markup=back_kb,
            )
        else:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            file_input = FSInputFile(file_path, filename=file_path.name)
            if media_type == "audio" and file_path.suffix.lower() in (".mp3", ".m4a"):
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=file_input,
                    caption=caption,
                    reply_markup=back_kb,
                    request_timeout=timeout,
                )
            else:
                await bot.send_document(
                    chat_id=chat_id,
                    document=file_input,
                    caption=caption,
                    reply_markup=back_kb,
                    request_timeout=timeout,
                )
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Отправить файл не удалось: {e!s}\n\n{caption}",
            reply_markup=back_kb,
        )
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass


async def _download_playlist(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    media_type: str,
    format_id: str,
) -> None:
    """Скачать весь плейлист локально (без отправки в Telegram)"""
    data = await state.get_data()
    playlist = data.get("playlist")
    if not playlist:
        await callback.message.edit_text("Ошибка: плейлист не найден.")
        await state.clear()
        return

    total = len(playlist)
    chat_id = callback.message.chat.id

    # Сообщение для прогресса (будет обновляться)
    progress_msg = await bot.send_message(
        chat_id,
        f"🎬 Начинаю скачивание плейлиста из {total} видео (тип: {media_type})\n"
        f"0/{total} завершено.\n\n"
        f"Файлы сохраняются в: {DOWNLOADS_DIR}\n"
        "Это может занять много времени...",
    )

    results = []
    for idx, video in enumerate(playlist, start=1):
        # Обновляем статус каждые 3 видео или каждые 10 секунд, но для простоты - после каждого
        await progress_msg.edit_text(
            f"🎬 Скачивание плейлиста\n"
            f"Прогресс: {idx-1}/{total} завершено. Обрабатывается видео {idx} из {total}...\n"
            f"Название: {video['title'][:50]}\n"
            f"Файлы сохраняются в: {DOWNLOADS_DIR}"
        )

        url = video['url']
        title = video['title']
        try:
            if media_type == "video":
                file_path, _ = await asyncio.to_thread(
                    download_video, url, DOWNLOADS_DIR, format_id=format_id
                )
            else:
                file_path, _ = await asyncio.to_thread(
                    download_audio, url, DOWNLOADS_DIR, format_id=format_id
                )
            results.append({"title": title, "success": True, "path": str(file_path)})
        except Exception as e:
            results.append({"title": title, "success": False, "error": str(e)})

        # Небольшая пауза между видео, чтобы не перегружать YouTube
        await asyncio.sleep(1)

    # Итоговое сообщение
    success_count = sum(1 for r in results if r["success"])
    fail_count = total - success_count
    final_text = (
        f"✅ Загрузка плейлиста завершена!\n"
        f"Всего видео: {total}\n"
        f"Успешно скачано: {success_count}\n"
        f"Ошибок: {fail_count}\n\n"
        f"Файлы сохранены в папку: {DOWNLOADS_DIR}\n"
    )
    if fail_count > 0:
        final_text += "\n❌ Список ошибок (первые 5):\n"
        for r in results:
            if not r["success"]:
                final_text += f"- {r['title']}: {r.get('error', 'Неизвестная ошибка')[:100]}\n"
                if len(final_text) > 3000:
                    final_text += "... и другие.\n"
                    break

    await progress_msg.edit_text(final_text, reply_markup=back_to_menu_kb())
    await state.clear()