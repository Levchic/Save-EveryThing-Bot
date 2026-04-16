from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards import back_to_menu_kb, main_menu_kb
from states import DownloadStates

router = Router()

TEXT_START = (
    "Привет! Я бот для скачивания видео и аудио с YouTube.\n\n"
    "Нажми «Скачать видео/аудио», затем отправь ссылку на видео или плейлист. "
    "Я предложу выбор: скачать видео или извлечь аудио, затем качество — после этого пришлю файл в чат.\n\n"
    "Чтобы не засорять чат, служебные сообщения (поиск, загрузка) я удаляю — остаются только готовые файлы и ссылка на источник."
)
TEXT_HELP = (
    "Как пользоваться:\n"
    "1. Нажми «Скачать видео/аудио».\n"
    "2. Отправь ссылку на видео YouTube (или на плейлист — будет обработано первое видео).\n"
    "3. Выбери: Видео или Только аудио.\n"
    "4. Выбери качество из списка.\n"
    "5. Дождись загрузки — файл придёт в чат.\n\n"
    "Если файл слишком большой (больше 50 МБ), пришлю прямую ссылку на скачивание.\n"
    "При ошибках (блокировка, регион, приватное видео) бот покажет описание проблемы."
)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await message.answer(TEXT_START, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(TEXT_START, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(TEXT_HELP, reply_markup=back_to_menu_kb())


@router.callback_query(F.data == "menu_download")
async def menu_download(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DownloadStates.waiting_link)
    # ID сообщения «Отправь ссылку» — потом удалим вместе с выбором качества
    await state.update_data(last_status_msg_id=None, menu_message_id=callback.message.message_id)
    await callback.answer()
    await callback.message.edit_text(
        "Отправь ссылку на видео или плейлист YouTube:\n"
        "Например: https://www.youtube.com/watch?v=...",
        reply_markup=back_to_menu_kb(),
    )
