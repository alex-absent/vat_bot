import asyncio
import json
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

DATA_FILE = "saved_vat.json"
LEGACY_LOG_FILE = "saved_vat.log"
FILE_LOCK = asyncio.Lock()
MAX_UPDATE_LIMIT = 10


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
    cleaned = re.sub(r"[\s\-]+", "", vat_number).upper()
    if re.fullmatch(r"TF\d+", cleaned):
        return f"26PL00{cleaned}"
    return cleaned


def is_valid_vat(vat_number: str) -> bool:
    return bool(re.fullmatch(r"(\d{2}PL00)?TF\d+", vat_number))


def _load_data_sync() -> dict[str, list[dict[str, str]]]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            return {}

    migrated: dict[str, list[dict[str, str]]] = {}
    if os.path.exists(LEGACY_LOG_FILE):
        with open(LEGACY_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) == 4:
                    dt, uid, vat, status = parts
                    status = status.replace("\\n", "\n")
                elif len(parts) == 3:
                    dt, uid, vat = parts
                    status = "Статус не сохранён"
                else:
                    continue

                migrated.setdefault(uid, []).append({
                    "dt": dt,
                    "vat": normalize_vat(vat),
                    "status": status,
                })
        if migrated:
            _save_data_sync(migrated)

    return migrated


def _save_data_sync(data: dict[str, list[dict[str, str]]]) -> None:
    tmp_file = f"{DATA_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)


async def save_vat(vat_number: str, user_id: int, status: str) -> bool:
    vat_number = normalize_vat(vat_number)
    uid_str = str(user_id)

    async with FILE_LOCK:
        data = _load_data_sync()
        user_list = data.setdefault(uid_str, [])

        for item in user_list:
            if item.get("vat") == vat_number:
                return False

        user_list.append({
            "dt": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
            "vat": vat_number,
            "status": status,
        })
        _save_data_sync(data)
        return True


async def find_saved_vat(user_id: int, vat_number: str) -> dict[str, str] | None:
    uid_str = str(user_id)
    vat_number = normalize_vat(vat_number)

    async with FILE_LOCK:
        data = _load_data_sync()
        for item in data.get(uid_str, []):
            if item.get("vat") == vat_number:
                return item
    return None


async def update_vat_status_in_file(user_id: int, vat_number: str, new_status: str) -> None:
    await bulk_update_vat_statuses_in_file(user_id, {normalize_vat(vat_number): new_status})


async def bulk_update_vat_statuses_in_file(user_id: int, status_map: dict[str, str]) -> None:
    if not status_map:
        return

    uid_str = str(user_id)
    normalized_map = {normalize_vat(k): v for k, v in status_map.items()}

    async with FILE_LOCK:
        data = _load_data_sync()
        user_list = data.get(uid_str, [])
        changed = False

        for item in user_list:
            vat = item.get("vat")
            if vat in normalized_map:
                item["status"] = normalized_map[vat]
                changed = True

        if changed:
            _save_data_sync(data)


async def get_user_numbers(user_id: int, limit: int = MAX_UPDATE_LIMIT) -> list[tuple[str, str, str]]:
    uid_str = str(user_id)

    async with FILE_LOCK:
        data = _load_data_sync()
        user_list = data.get(uid_str, [])
        return [
            (item.get("dt", ""), item.get("vat", ""), item.get("status", "Статус не сохранён"))
            for item in user_list[-limit:]
        ]


async def delete_user_numbers(user_id: int) -> None:
    uid_str = str(user_id)

    async with FILE_LOCK:
        data = _load_data_sync()
        if uid_str in data:
            del data[uid_str]
            _save_data_sync(data)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Добро пожаловать в VAT TAX FREE Bot\n\n"
        "📷 Отправьте фото чека или выберите действие в меню.",
        reply_markup=get_main_keyboard(),
    )


async def vat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Пример:\n/vat 26PL00TF003976030")
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
        user_id = update.effective_user.id

        existing = await find_saved_vat(user_id, vat_number)
        if existing:
            keyboard = [
                [InlineKeyboardButton("🔍 Проверить актуальный статус", callback_data=f"check:{vat_number}")],
                [InlineKeyboardButton("📋 Мои номера", callback_data="my_numbers")],
            ]
            await update.message.reply_text(
                f"ℹ️ Этот документ уже есть в сохранённых:\n\n"
                f"📄 {vat_number}\n"
                f"🕒 Добавлен: {existing.get('dt', '')}\n"
                f"📌 Статус: {existing.get('status', 'Неизвестно')}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

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
        numbers = await get_user_numbers(user_id, limit=MAX_UPDATE_LIMIT)
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
        numbers = await get_user_numbers(user_id, limit=MAX_UPDATE_LIMIT)
        if not numbers:
            await update.message.reply_text("📭 У вас пока нет сохранённых номеров")
            return

        result = "📋 Мои номера:\n\n"
        for dt, vat, status in reversed(numbers):
            result += f"🕒 {dt}\n📄 {vat}\n📌 {status}\n\n"

        await update.message.reply_text(result)
        return

    if "Обновить статусы" in text:
        numbers_to_process = await get_user_numbers(user_id, limit=MAX_UPDATE_LIMIT)
        if not numbers_to_process:
            await update.message.reply_text("📭 У вас пока нет сохранённых номеров")
            return

        ordered_numbers = list(reversed(numbers_to_process))
        total = len(ordered_numbers)

        to_fetch = [
            vat for _, vat, status in ordered_numbers
            if "Возврат выплачен" not in status
        ]

        if to_fetch:
            msg = await update.message.reply_text(
                f"⏳ Проверяю {len(to_fetch)} из {total} док. (выплаченные пропускаются)..."
            )
        else:
            msg = await update.message.reply_text("⏳ Формирую список статусов...")

        semaphore = asyncio.Semaphore(5)

        async def fetch_status(vat_number: str) -> tuple[str, str]:
            async with semaphore:
                new_status = await asyncio.to_thread(get_vat_status, vat_number)
                return vat_number, new_status

        updated_map: dict[str, str] = {}
        if to_fetch:
            fetched_results = await asyncio.gather(*(fetch_status(vat) for vat in to_fetch))
            updated_map = dict(fetched_results)
            await bulk_update_vat_statuses_in_file(user_id, updated_map)

        text_result = f"✅ Обновление завершено ({total}/{MAX_UPDATE_LIMIT}):\n\n"
        for _, vat_number, old_status in ordered_numbers:
            if vat_number in updated_map:
                final_status = updated_map[vat_number]
            else:
                final_status = f"{old_status} (пропущено)"
            text_result += f"📄 {vat_number}\n📌 {final_status}\n\n"

        await msg.edit_text(text_result)
        return

    vat_number = normalize_vat(text)
    if not is_valid_vat(vat_number):
        await update.message.reply_text(
            "❓ Неизвестная команда или неверный формат номера.\n"
            "Отправьте фото чека или введите номер вида 26PL00TF003976030."
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
