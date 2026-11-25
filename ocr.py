import re
import pytesseract
import zxingcpp
from PIL import Image, ImageEnhance, ImageOps


def preprocess_image(img: Image.Image) -> Image.Image:
    img = img.convert("L")

    # Ограничиваем максимальный размер, чтобы Tesseract не тормозил на больших фото
    scale = 2 if img.width > 1200 else 3
    img = img.resize(
        (img.width * scale, img.height * scale),
        Image.LANCZOS,
    )

    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.point(lambda x: 255 if x > 160 else 0, mode="1")
    return img


def clean_text(text: str) -> str:
    text = text.upper()
    text = text.replace(" ", "")
    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace("-", "")
    text = text.replace("O", "0")
    return text


def find_vat(text: str) -> str | None:
    text = clean_text(text)
    print("CLEAN TEXT:", text)

    match = re.search(r"(25|26|27)PL00TF\d{6,}", text)
    if match:
        vat = match.group(0)
        print("FULL VAT FOUND:", vat)
        return vat

    match = re.search(r"TF\d{6,}", text)
    if match:
        short_vat = match.group(0)
        # Восстанавливаем полный номер
        vat = f"26PL00{short_vat}"
        print("RESTORED VAT:", vat)
        return vat

    return None


def extract_barcode_number(img: Image.Image) -> str | None:
    """Попытка 0: Быстрое чтение штрихкода Code 128."""
    gray = img.convert("L")
    for variant in (img, gray, ImageOps.autocontrast(gray)):
        results = zxingcpp.read_barcodes(variant)
        for res in results:
            vat = find_vat(res.text)
            if vat:
                print("BARCODE VAT FOUND:", vat)
                return vat
    return None


def extract_sticker_number(img: Image.Image) -> str | None:
    width, height = img.size

    number_zone = img.crop((0, int(height * 0.78), width, height))
    number_zone = number_zone.convert("L")

    # Адаптивное масштабирование: приводим высоту зоны к ~400px вместо жёсткого x15
    target_height = 400
    scale = max(1, min(6, round(target_height / max(1, number_zone.height))))

    number_zone = number_zone.resize(
        (number_zone.width * scale, number_zone.height * scale),
        Image.LANCZOS,
    )
    number_zone = ImageEnhance.Contrast(number_zone).enhance(4)

    text = pytesseract.image_to_string(
        number_zone,
        lang="eng",
        config="--psm 7",
    )

    print("=" * 50)
    print("STICKER OCR:")
    print(text)
    print("=" * 50)

    return find_vat(text)


def extract_taxfree_number(image_path: str) -> str | None:
    with Image.open(image_path) as raw_img:
        # Исправляем ориентацию фото с телефона по EXIF
        img = ImageOps.exif_transpose(raw_img)
        print(f"IMAGE SIZE: {img.width}x{img.height}")

        # Попытка 0: Штрихкод (самый быстрый и точный способ)
        vat = extract_barcode_number(img)
        if vat:
            return vat

        # Попытка 1: Наклейка внизу
        vat = extract_sticker_number(img)
        if vat:
            print("VAT FOUND IN STICKER:", vat)
            return vat

        # Попытка 2: Полное фото
        processed = preprocess_image(img)
        text = pytesseract.image_to_string(
            processed,
            lang="pol+eng",
            config="--psm 6",
        )

        print("=" * 50)
        print("OCR RAW:")
        print(text)
        print("=" * 50)

        vat = find_vat(text)
        if vat:
            return vat

        # Попытка 3: Верх документа
        width, height = img.size
        top = img.crop((0, 0, width, int(height * 0.4)))
        top = preprocess_image(top)

        text = pytesseract.image_to_string(
            top,
            lang="pol+eng",
            config="--psm 6",
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
