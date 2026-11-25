import asyncio
import os
import re
import tempfile
from datetime import datetime

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from ocr import extract_taxfree_number
from vat_status import get_vat_status

LOG_FILE = "saved_vat.log"
FILE_LOCK = asyncio.Lock()


def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📷 Сканировать VAT")],
        [KeyboardButton("📋 Мои номера")],
        [KeyboardButton("🔍 Проверить номер")],
        [KeyboardButton("🔄 Обновить статусы")],
        [KeyboardButton("🗑 Удалить все записи")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def normalize_vat(vat_number: str) -> str:
    return vat_number.strip().upper()


def is_valid_vat(vat_number: str) -> bool:
    return bool(re.fullmatch(r"(\d{2}PL00)?TF\d+", vat_number))


def _encode_status(status: str) -> str:
    return status.replace("\n", "\\n").replace(";", ",")


def _decode_status(status: str) -> str:
    return status.replace("\\n", "\n")


async def save_vat(vat_number: str, user_id: int, status: str) -> bool:
    vat_number = normalize_vat(vat_number)
    uid_str = str(user_id)
    safe_status = _encode_status(status)

    async with FILE_LOCK:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(";")
                    if len(parts) >= 3 and parts[1] == uid_str and parts[2] == vat_number:
                        return False

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            dt = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
            f.write(f"{dt};{uid_str};{vat_number};{safe_status}\n")

        return True


async def update_vat_status_in_file(user_id: int, vat_number: str, new_status: str) -> None:
    uid_str = str(user_id)
    vat_number = normalize_vat(vat_number)
    safe_status = _encode_status(new_status)

    async with FILE_LOCK:
        if not os.path.exists(LOG_FILE):
            return

        updated_lines = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) >= 3 and parts[1] == uid_str and parts[2] == vat_number:
                    dt = parts[0]
                    updated_lines.append(f"{dt};{uid_str};{vat_number};{safe_status}\n")
                else:
                    updated_lines.append(line)

        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)


async def get_user_numbers(user_id: int, limit: int = 20) -> list[tuple[str, str, str]]:
    uid_str = str(user_id)
    result = []

    async with FILE_LOCK:
        if not os.path.exists(LOG_FILE):
            return []

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) == 4:
                    dt, uid, vat, status = parts
                elif len(parts) == 3:
                    dt, uid, vat = parts
                    status = "Статус не сохранён"
                else:
                    continue

                if uid == uid_str:
                    result.append((dt, vat, _decode_status(status)))

    return result[-limit:]


async def get_active_numbers(user_id: int) -> list[tuple[str, str]]:
    all_numbers = await get_user_numbers(user_id, limit=100)
    return [
        (vat, status)
        for _, vat, status in all_numbers
        if "Возврат выплачен" not in status
    ]


async def delete_user_numbers(user_id: int) -> None:
    uid_str = str(user_id)

    async with FILE_LOCK:
        if not os.path.exists(LOG_FILE):
            return

        kept_lines = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) >= 2 and parts[1] != uid_str:
                    kept_lines.append(line)

        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Добро пожаловать в VAT TAX FREE Bot\n\n"
        "📷 Отправьте фото чека или выберите действие в меню.",
        reply_markup=get_main_keyboard(),
    )


async def vat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Пример:\n/vat TF003976030")
        return

    vat_number = normalize_vat(context.args[0])
    if not is_valid_vat(vat_number):
        await update.message.reply_text("❌ Неверный формат номера TAX FREE.")
        return

    msg = await update.message.reply_text(f"⏳ Проверяю статус...\n\n{vat_number}")
    status = await asyncio.to_thread(get_vat_status, vat_number)
    await msg.edit_text(f"📄 TAX FREE\n\n{vat_number}\n\n{status}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filename = None
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            filename = tmp.name

        await file.download_to_drive(filename)

        vat_number = await asyncio.to_thread(extract_taxfree_number, filename)
        if not vat_number:
            await update.message.reply_text("❌ Номер TAX FREE не найден на фото")
            return

        vat_number = normalize_vat(vat_number)

        keyboard = [
            [InlineKeyboardButton("🔍 Проверить статус", callback_data=f"check:{vat_number}")],
            [InlineKeyboardButton("💾 Сохранить номер", callback_data=f"save:{vat_number}")],
            [InlineKeyboardButton("📋 Мои номера", callback_data="my_numbers")],
        ]

        await update.message.reply_text(
            f"🔍 Найден номер:\n\n{vat_number}\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при обработке фото:\n{e}")

    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "my_numbers":
        numbers = await get_user_numbers(user_id)
        if not numbers:
            await query.edit_message_text("📭 У вас пока нет сохранённых номеров")
            return

        text = "📋 Мои номера:\n\n"
        for dt, vat, status in reversed(numbers):
            text += f"🕒 {dt}\n📄 {vat}\n📌 {status}\n\n"

        await query.edit_message_text(text)
        return

    if ":" not in data:
        return

    action, vat_number = data.split(":", 1)

    if action == "save":
        await query.edit_message_text(f"💾 Получаю статус и сохраняю...\n\n{vat_number}")
        status = await asyncio.to_thread(get_vat_status, vat_number)
        saved = await save_vat(vat_number, user_id, status)

        if not saved:
            await update_vat_status_in_file(user_id, vat_number, status)
            await query.edit_message_text(
                f"ℹ️ Номер уже был в списке (статус обновлён):\n\n{vat_number}\n\n{status}"
            )
            return

        await query.edit_message_text(f"✅ Сохранено:\n\n{vat_number}\n\n{status}")
        return

    if action == "check":
        await query.edit_message_text(f"⏳ Проверяю статус...\n\n{vat_number}")
        status = await asyncio.to_thread(get_vat_status, vat_number)
        await query.edit_message_text(f"📄 TAX FREE\n\n{vat_number}\n\n{status}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if "Сканировать VAT" in text:
        await update.message.reply_text("📷 Отправьте фотографию документа TAX FREE")
        return

    if "Проверить номер" in text:
        await update.message.reply_text(
            "Введите номер TAX FREE\n\nНапример:\n26PL00TF003976030 или TF003976030"
        )
        return

    if "Удалить все записи" in text:
        await delete_user_numbers(user_id)
        await update.message.reply_text(
            "✅ Все ваши сохранённые номера удалены.",
            reply_markup=get_main_keyboard(),
        )
        return

    if "Мои номера" in text:
        numbers = await get_user_numbers(user_id)
        if not numbers:
            await update.message.reply_text("📭 У вас пока нет сохранённых номеров")
            return

        result = "📋 Мои номера:\n\n"
        for dt, vat, status in reversed(numbers):
            result += f"🕒 {dt}\n📄 {vat}\n📌 {status}\n\n"

        await update.message.reply_text(result)
        return

    if "Обновить статусы" in text:
        all_numbers = await get_user_numbers(user_id)
        if not all_numbers:
            await update.message.reply_text("📭 У вас пока нет сохранённых номеров")
            return

        active_numbers = await get_active_numbers(user_id)
        if not active_numbers:
            await update.message.reply_text(
                "✅ Все ваши документы уже имеют статус '💰 Возврат выплачен'"
            )
            return

        msg = await update.message.reply_text("⏳ Подготовка проверки...")
        results = []
        total = len(active_numbers)

        for index, (vat_number, _) in enumerate(active_numbers, start=1):
            progress = "🟩" * index + "⬜" * (total - index)
            await msg.edit_text(
                f"⏳ Проверяю {index}/{total}\n\n{vat_number}\n\n{progress}"
            )

            new_status = await asyncio.to_thread(get_vat_status, vat_number)
            await update_vat_status_in_file(user_id, vat_number, new_status)
            results.append((vat_number, new_status))

        text_result = "✅ Обновление завершено:\n\n"
        for vat_number, status in results:
            text_result += f"📄 {vat_number}\n📌 {status}\n\n"

        await msg.edit_text(text_result)
        return

    vat_number = normalize_vat(text)
    if not is_valid_vat(vat_number):
        await update.message.reply_text(
            "❓ Неизвестная команда или неверный формат номера.\n"
            "Отправьте фото чека или введите номер вида TF003976030."
        )
        return

    msg = await update.message.reply_text(f"⏳ Проверяю статус...\n\n{vat_number}")
    status = await asyncio.to_thread(get_vat_status, vat_number)

    keyboard = [[InlineKeyboardButton("💾 Сохранить номер", callback_data=f"save:{vat_number}")]]
    await msg.edit_text(
        f"📄 TAX FREE\n\n{vat_number}\n\n{status}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("vat", "Проверить номер"),
    ])


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vat", vat_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
