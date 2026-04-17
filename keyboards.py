from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📥 Скачать видео/аудио", callback_data="menu_download"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ Как пользоваться", callback_data="menu_help"),
    )
    return builder.as_markup()


def type_choice_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎬 Видео", callback_data="type_video"),
        InlineKeyboardButton(text="🎵 Только аудио", callback_data="type_audio"),
    )
    builder.row(InlineKeyboardButton(text="◀️ В меню", callback_data="menu_back"))
    return builder.as_markup()


def video_quality_kb(formats: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for f in formats:
        height = f.get("height")
        if height:
            label = f.get("label", f"{height}p")
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"quality_v_{height}")])
    # Добавляем кнопку назад
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="quality_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def audio_quality_kb(formats: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in formats:
        builder.row(
            InlineKeyboardButton(
                text=f.get("label", f.get("format_id", "?")),
                callback_data=f"quality_a_{f.get('format_id', '')}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="quality_back"))
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu_back"))
    return builder.as_markup()


def playlist_action_kb(confirm: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для выбора действия с плейлистом"""
    if confirm:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, скачать все", callback_data="playlist_confirm_yes")],
            [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="playlist_confirm_no")],
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Скачать только первое видео", callback_data="playlist_first_only")],
            [InlineKeyboardButton(text="💾 Скачать весь плейлист локально", callback_data="playlist_full_local")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")],
        ])

