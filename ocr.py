import re
import pytesseract

from PIL import (
    Image,
    ImageEnhance
)


def preprocess_image(img):

    img = img.convert("L")

    img = img.resize(
        (
            img.width * 3,
            img.height * 3
        ),
        Image.LANCZOS
    )

    img = ImageEnhance.Contrast(
        img
    ).enhance(2.5)

    img = img.point(
        lambda x: 255 if x > 160 else 0,
        mode="1"
    )

    return img


def clean_text(text):

    text = text.upper()

    text = text.replace(" ", "")
    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace("-", "")

    text = text.replace("O", "0")

    return text


def find_vat(text):

    text = clean_text(text)

    print("CLEAN TEXT:", text)

    match = re.search(
        r"(25|26|27)PL00TF\d{6,}",
        text
    )

    if match:

        vat = match.group(0)

        print(
            "FULL VAT FOUND:",
            vat
        )

        return vat

    match = re.search(
        r"TF\d{6,}",
        text
    )

    if match:

        short_vat = match.group(0)

        # Восстанавливаем полный номер
        vat = f"26PL00{short_vat}"

        print(
            "RESTORED VAT:",
            vat
        )

        return vat

    return None

def extract_sticker_number(img):

    width, height = img.size

    number_zone = img.crop(
        (
            0,
            int(height * 0.78),
            width,
            height
        )
    )

    number_zone = number_zone.convert("L")

    number_zone = number_zone.resize(
        (
            number_zone.width * 15,
            number_zone.height * 15
        ),
        Image.LANCZOS
    )

    number_zone = ImageEnhance.Contrast(
        number_zone
    ).enhance(6)

    text = pytesseract.image_to_string(
        number_zone,
        lang="eng",
        config="--psm 7"
    )

    print("=" * 50)
    print("STICKER OCR:")
    print(text)
    print("=" * 50)

    text = clean_text(text)

    print("STICKER CLEAN:")
    print(text)

    match = re.search(
        r"(25|26|27)PL00TF\d{6,}",
        text
    )

    if match:

        vat = match.group(0)

        print(
            "STICKER VAT FOUND:",
            vat
        )

        return vat

    return None


def extract_taxfree_number(image_path):

    img = Image.open(image_path)

    print(
        f"IMAGE SIZE: {img.width}x{img.height}"
    )

    #
    # Попытка 1
    # Наклейка
    #

    vat = extract_sticker_number(img)

    if vat:

        print(
            "VAT FOUND IN STICKER:",
            vat
        )

        return vat

    #
    # Попытка 2
    # Полное фото
    #

    processed = preprocess_image(img)

    text = pytesseract.image_to_string(
        processed,
        lang="pol+eng",
        config="--psm 6"
    )

    print("=" * 50)
    print("OCR RAW:")
    print(text)
    print("=" * 50)

    vat = find_vat(text)

    if vat:
        return vat

    #
    # Попытка 3
    # Верх документа
    #

    width, height = img.size

    top = img.crop(
        (
            0,
            0,
            width,
            int(height * 0.4)
        )
    )

    top = preprocess_image(top)

    text = pytesseract.image_to_string(
        top,
        lang="pol+eng",
        config="--psm 6"
    )

    print("=" * 50)
    print("TOP OCR:")
    print(text)
    print("=" * 50)

    vat = find_vat(text)

    if vat:
        return vat

    print("VAT NOT FOUND")

    return None