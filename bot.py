import asyncio
import tempfile
import re
import os
from datetime import datetime
from telegram import BotCommand

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from ocr import extract_taxfree_number
from config import BOT_TOKEN
from vat_status import get_vat_status


LOG_FILE = "saved_vat.log"

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📷 Сканировать VAT")],
        [KeyboardButton("📋 Мои номера")],
        [KeyboardButton("🔍 Проверить номер")],
        [KeyboardButton("🔄 Обновить статусы")],
        [KeyboardButton("🗑 Удалить все записи")]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

def get_last_numbers(limit=20):
    try:
        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            lines = f.readlines()

        return lines[-limit:]

    except FileNotFoundError:
        return []

def normalize_vat(vat_number):

    vat_number = vat_number.strip().upper()

    if re.match(r"\d{2}PL00TF\d+", vat_number):
        return vat_number

    if vat_number.startswith("TF"):
        return vat_number

    return vat_number

def number_exists(user_id, vat_number):
    if not os.path.exists(LOG_FILE):
        return False

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(";")

            if len(parts) >= 3:
                uid = parts[1]
                vat = parts[2]

                if uid == str(user_id) and vat == vat_number:
                    return True

    return False

def get_user_numbers(
    user_id,
    limit=20
):

    print("SEARCH USER:", user_id)

    try:

        result = []

        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                print("RAW LINE:", line.strip())

                parts = line.strip().split(";")

                print("PARTS:", parts)

                if len(parts) == 4:

                    dt, uid, vat, status = parts

                elif len(parts) == 3:

                    dt, uid, vat = parts
                    status = "Статус не сохранён"

                else:

                    print("SKIP BAD LINE")
                    continue

                print("UID FROM FILE:", uid)
                print("USER REQUEST:", user_id)

                if uid == str(user_id):

                    print("MATCH FOUND!")

                    result.append(
                        (
                            dt,
                            vat,
                            status
                        )
                    )

        print("RESULT:", result)

        return result[-limit:]

    except FileNotFoundError:

        print("FILE NOT FOUND")

        return []

def save_vat(
    vat_number,
    user_id,
    status
):
    vat_number = normalize_vat(vat_number)
    
    if number_exists(user_id, vat_number):
        return False

    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"{datetime.now():%Y-%m-%d %H:%M:%S};"
            f"{user_id};"
            f"{vat_number};"
            f"{status}\n"
        )

    return True
    
def delete_user_numbers(user_id):
    print("DELETE USER:", user_id)

    if not os.path.exists(LOG_FILE):
        print("LOG FILE NOT FOUND")
        return

    lines = []

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(";")

            print("LINE:", parts)

            if len(parts) >= 2:
                uid = parts[1]

                if uid != str(user_id):
                    lines.append(line)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("DELETE COMPLETE")   

def get_last_numbers(limit=20):

    try:
        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return f.readlines()[-limit:]

    except FileNotFoundError:
        return []
        
def get_active_numbers(user_id):

    result = []

    try:

        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                parts = line.strip().split(";")

                if len(parts) != 4:
                    continue

                dt, uid, vat, status = parts

                if uid != str(user_id):
                    continue

                if status == "💰 Возврат выплачен":
                    continue

                result.append(
                    (vat, status)
                )

    except FileNotFoundError:
        pass

    return result
        
 
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Добро пожаловать в VAT TAX FREE Bot\n\n"
        "📷 Отправьте фото чека\n"
        "или выберите действие в меню.",
        reply_markup=get_main_keyboard()
    )    

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:

        photo = update.message.photo[-1]

        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        ) as tmp:

            await file.download_to_drive(
                tmp.name
            )

            filename = tmp.name

        vat_number = extract_taxfree_number(
            filename
        )

        if not vat_number:
            await update.message.reply_text(
                "❌ Номер TAX FREE не найден"
            )
            return

        vat_number = normalize_vat(
            vat_number
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔍 Проверить статус",
                    callback_data=f"check:{vat_number}"
                )
            ],
            [
                InlineKeyboardButton(
                    "💾 Сохранить номер",
                    callback_data=f"save:{vat_number}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Мои номера",
                    callback_data="my_numbers"
                )
            ]
        ]

        markup = InlineKeyboardMarkup(
            keyboard
        )

        await update.message.reply_text(
            f"🔍 Найден номер:\n\n"
            f"{vat_number}\n\n"
            f"Выберите действие:",
            reply_markup=markup
        )

    except Exception as e:

        await update.message.reply_text(
            f"Ошибка OCR:\n{e}"
        )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "my_numbers":

        numbers = get_user_numbers(
            query.from_user.id
        )

        if not numbers:

            await query.edit_message_text(
                "📭 У вас пока нет сохранённых номеров"
            )

            return

        text = "📋 Мои номера\n\n"

        for dt, vat, status in reversed(numbers):

            text += (
                f"{dt}\n"
                f"{vat}\n"
                f"{status}\n\n"
            )

        await query.edit_message_text(
            text
        )

        return

    action, vat_number = data.split(
        ":",
        1
    )

    if action == "save":

        await query.edit_message_text(
            f"💾 Сохраняю...\n\n{vat_number}"
        )

        status = await asyncio.to_thread(
            get_vat_status,
            vat_number
        )

        saved = save_vat(
            vat_number,
            update.effective_user.id,
            status
        )

        if not saved:
            await update.message.reply_text(
                "ℹ️ Такой номер уже сохранён"
            )
            return

        await query.edit_message_text(
            f"✅ Сохранено\n\n"
            f"{vat_number}\n\n"
            f"{status}"
        )

        return

    if action == "check":

        await query.edit_message_text(
            f"⏳ Проверяю статус...\n\n"
            f"{vat_number}"
        )

        status = await asyncio.to_thread(
            get_vat_status,
            vat_number
        )

        await query.edit_message_text(
            f"📄 TAX FREE\n\n"
            f"{vat_number}\n\n"
            f"{status}"
        )

        return

async def vat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Пример:\n"
            "/vat TF003976030"
        )

        return

    vat_number = normalize_vat(
        context.args[0]
    )

    status = await asyncio.to_thread(
        get_vat_status,
        vat_number
    )

    await update.message.reply_text(
        f"📄 TAX FREE\n\n"
        f"{vat_number}\n\n"
        f"{status}"
    )

async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("vat", "Проверить номер")
    ])

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()
    
    if text == "🗑 Удалить все записи":

        delete_user_numbers(
            update.effective_user.id
        )

        await update.message.reply_text(
            "✅ Все сохранённые номера удалены",
            reply_markup=get_main_keyboard()
        )

        return
    
    print("TEXT=", repr(text))

    if "Мои номера" in text:

        numbers = get_user_numbers(
            update.message.from_user.id
        )

        if not numbers:
            await update.message.reply_text(
                "📭 У вас пока нет сохранённых номеров"
            )
            return

        result = "📋 Мои номера\n\n"

        for dt, vat, status in reversed(numbers):

            result += (
                f"{dt}\n"
                f"{vat}\n"
                f"{status}\n\n"
            )

        await update.message.reply_text(
            result
        )

        return

    if "Проверить номер" in text:

        await update.message.reply_text(
            "Введите номер TAX FREE\n\n"
            "Например:\n"
            "26PL00TF003976030 (или TF003976030)"
        )

        return
        
    if "Удалить все записи" in text:
        print("DELETE BUTTON PRESSED")
        delete_user_numbers(update.effective_user.id)

        await update.message.reply_text(
            "✅ Все ваши сохранённые номера удалены.",
            reply_markup=get_main_keyboard()
        )
        return
    
    if "Обновить статусы" in text:

        numbers = get_active_numbers(
            update.message.from_user.id
        )

        if not numbers:

            await update.message.reply_text(
                "✅ Все документы уже имеют статус "
                "'💰 Возврат выплачен'"
            )

            return

        msg = await update.message.reply_text(
            "⏳ Подготовка проверки..."
        )

        results = []

        total = len(numbers)

        for index, (vat_number, old_status) in enumerate(
            numbers,
            start=1
        ):

            progress = (
                "🟩" * index +
                "⬜" * (total - index)
            )

            await msg.edit_text(
                f"⏳ Проверяю {index}/{total}\n\n"
                f"{vat_number}\n\n"
                f"{progress}"
            )

            status = await asyncio.to_thread(
                get_vat_status,
                vat_number
            )

            results.append(
                (
                    vat_number,
                    status
                )
            )

        text_result = (
            "✅ Обновление завершено\n\n"
        )

        for vat_number, status in results:

            text_result += (
                f"{vat_number}\n"
                f"{status}\n\n"
            )

        await msg.edit_text(
        text_result
        )

        return   

    if "Сканировать чек" in text:

        await update.message.reply_text(
            "📷 Отправьте фотографию документа TAX FREE"
        )

        return

    vat_number = normalize_vat(text)

    status = await asyncio.to_thread(
        get_vat_status,
        vat_number
    )

    await update.message.reply_text(
        f"📄 TAX FREE\n\n"
        f"{vat_number}\n\n"
        f"{status}"
    )

def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "vat",
            vat
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT &
            ~filters.COMMAND,
            text_handler
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()