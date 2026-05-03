"""Tesseract OCR wrapper — magyar+angol+német (HU+EN+DE) nyelvi modellek.

A pdf_loader 3-szintű fallback-jénél a 2. réteg: ha a PyMuPDF natív szöveg
< SCANNED_THRESHOLD karakter, akkor az oldal-renderelt képet átadjuk a
Tesseract-nak. Ha az OCR még mindig kevés szöveget ad, az oldal `is_scanned=True`
marad és a PageContent `image_bytes`-szal tölt fel — a vision-extract node majd
közvetlenül a képből nyer ki strukturált adatot.

Lazy-importáljuk a pytesseract és Pillow-t, hogy a Fázis 1 dummy-csak smoke
teszt NE igényelje a tesseract-rendszerszintű telepítést.
"""

from __future__ import annotations

# Threshold: ha PyMuPDF natív szövege < ennyi karakter, az oldal szkennelt
SCANNED_THRESHOLD = 50

# Tesseract nyelvi kombináció — magyar+angol+német, mert a teszt-adat háromnyelvű
TESSERACT_LANGS = "hun+eng+deu"


def tesseract_available() -> bool:
    """Visszaadja, hogy a pytesseract + tesseract-binary működik-e.

    Lazy-import: ha a package nincs telepítve vagy a tesseract binary nem érhető
    el, False-t ad vissza, és a downstream PDF loader skip-eli az OCR réteget.
    """
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_image_bytes(image_bytes: bytes, langs: str = TESSERACT_LANGS) -> str:
    """Bináris kép → szöveg Tesseract OCR-rel.

    Hibák esetén (Tesseract hiányzik, kép-formátum nem támogatott) üres stringet
    ad vissza — a PageContent `image_bytes` mezője megmarad, a downstream
    vision-fallback fogja a feladatot átvenni.
    """
    if not image_bytes:
        return ""

    try:
        from io import BytesIO

        import pytesseract
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as img:
            # PNG-ben tárolt alpha-csatornás kép → RGB konverzió a Tesseractnak
            if img.mode != "RGB":
                img = img.convert("RGB")
            return pytesseract.image_to_string(img, lang=langs).strip()
    except Exception:
        return ""
