"""Normalización de títulos de publicación para el matching cross-retailer.

Cada tienda escribe el mismo producto distinto: "Apple iPhone 13 128GB Midnight",
"CELULAR APPLE IPHONE 13 128 GB NEGRO", "iPhone 13 (128 Gb) Medianoche". El matcher
necesita una representación estable de la que salgan una clave determinística
(marca + modelo + capacidad) y un conjunto de tokens para comparar por similitud.

Sin dependencias nuevas a propósito: es texto corto y volumen bajo (miles de filas por
corrida), y una implementación propia de Jaccard sobre tokens acierta lo suficiente para
esta categoría. Si en el futuro hace falta más recall (categorías sin modelo explícito,
como electrodomésticos genéricos), ahí entra la vía de embeddings.
"""

from __future__ import annotations

import re
import unicodedata

#: Palabras que ninguna tienda usa de forma consistente y que solo agregan ruido.
STOPWORDS = frozenset(
    {
        "celular", "celulares", "smartphone", "telefono", "movil",
        "notebook", "laptop", "computadora", "pc",
        "tv", "televisor", "smart", "smarttv",
        "nuevo", "nueva", "original", "oficial", "sellado", "liberado",
        "desbloqueado", "libre", "gtia", "garantia",
        "color", "con", "sin", "de", "del", "la", "el", "los", "las", "y", "para",
        "pulgadas", "pulg", "cm",
        "envio", "gratis", "cuotas", "oferta",
    }
)

#: Colores: se sacan de los tokens de similitud (una tienda dice "Midnight", otra
#: "Medianoche", otra "Negro") pero se guardan aparte como atributo.
COLOR_WORDS = frozenset(
    {
        "negro", "black", "midnight", "medianoche", "grafito", "space", "gris", "gray",
        "blanco", "white", "starlight", "plata", "silver", "plateado",
        "azul", "blue", "celeste", "verde", "green", "rojo", "red", "product",
        "rosa", "pink", "violeta", "purple", "morado", "dorado", "gold", "amarillo",
        "titanio", "titanium", "beige", "crema", "naranja", "orange",
    }
)

#: Marcas frecuentes en electro/tecnología AR. Se usa solo como guarda del matcher
#: (marcas distintas nunca se agrupan); una marca ausente de esta lista simplemente no
#: aporta la guarda, no rompe el matching.
BRANDS = frozenset(
    {
        "apple", "samsung", "motorola", "xiaomi", "nokia", "huawei", "honor", "tcl",
        "lenovo", "asus", "acer", "hp", "dell", "msi", "gigabyte", "banghó", "bangho",
        "lg", "philips", "noblex", "hitachi", "bgh", "sony", "panasonic", "jvc",
        "whirlpool", "drean", "gafa", "patrick", "electrolux", "candy", "longvie",
        "peabody", "atma", "liliana", "oster", "philco", "smartlife", "hisense",
        "jbl", "bose", "logitech", "redragon", "razer", "corsair", "kingston", "seagate",
        "nintendo", "playstation", "xbox", "microsoft", "amazon", "google", "intel", "amd",
    }
)

_CAPACITY_RE = re.compile(r"\b(\d+)\s*(gb|tb|mb)\b")
# Sin `\b` final: `"` no es carácter de palabra, así que un límite después de las
# comillas nunca matchea (`50"` quedaba sin detectar).
_SCREEN_RE = re.compile(r"\b(\d{2}(?:[.,]\d)?)\s*(?:\"|''|pulgadas|pulg|inch)")
_MODEL_NUM_RE = re.compile(r"\b([a-z]*\d+[a-z0-9]*)\b")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize_text(text: str) -> str:
    """minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    cleaned = strip_accents(text.lower())
    cleaned = re.sub(r"[^\w\s\".']", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_capacity_gb(text: str) -> int | None:
    """Capacidad de almacenamiento en GB. `1 TB` -> 1024, `128GB` -> 128.

    Un título de notebook trae dos cifras en GB ("8GB 512GB": RAM y disco). Se toma la
    mayor: el almacenamiento es lo que distingue dos SKUs del mismo modelo, y usar la
    primera agarraba la RAM.
    """
    values: list[int] = []
    for raw_value, unit in _CAPACITY_RE.findall(normalize_text(text)):
        value = int(raw_value)
        if unit == "tb":
            value *= 1024
        elif unit == "mb":
            value = max(1, value // 1024)
        values.append(value)
    return max(values) if values else None


def extract_screen_inches(text: str) -> float | None:
    match = _SCREEN_RE.search(normalize_text(text))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def extract_color(text: str) -> str | None:
    for token in normalize_text(text).split():
        if token in COLOR_WORDS:
            return token
    return None


#: Sufijos que cambian el producto aunque el resto del título sea idéntico: un
#: "iPhone 13" y un "iPhone 13 Pro Max" comparten casi todos los tokens. Si dos títulos
#: no coinciden en este conjunto, no son el mismo producto.
VARIANT_MARKERS = frozenset({"mini", "pro", "max", "plus", "ultra", "lite", "air", "se"})

#: Código de modelo del fabricante: alfanumérico con letras y dígitos mezclados y al
#: menos 4 caracteres (`15-fc0235la`, `50s5k`, `un50u8000f`, `mt5010`). Cuando dos
#: títulos traen uno, es la señal más fuerte que existe sin id de catálogo.
_MODEL_CODE_RE = re.compile(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9]{2,}(?:-[a-z0-9]+)*\b")


def extract_variants(text: str) -> frozenset[str]:
    return frozenset(t for t in normalize_text(text).split() if t in VARIANT_MARKERS)


def extract_model_codes(text: str) -> frozenset[str]:
    """Códigos de modelo del título, sin guiones (así `15-fc0235la` == `15fc0235la`)."""
    normalized = _CAPACITY_RE.sub(" ", normalize_text(text))
    normalized = _SCREEN_RE.sub(" ", normalized)
    codes = set()
    for match in _MODEL_CODE_RE.finditer(normalized):
        code = match.group(0).replace("-", "")
        if len(code) >= 5 and code not in COLOR_WORDS:
            codes.add(code)
    return frozenset(codes)


def extract_brand(text: str) -> str | None:
    """Primera marca conocida que aparece en el título. None si no hay ninguna."""
    for token in normalize_text(text).split():
        if token in BRANDS:
            return token
    return None


def tokens_for_similarity(text: str) -> frozenset[str]:
    """Tokens significativos: sin stopwords, sin colores, sin tokens de 1 carácter.

    La capacidad se conserva (distingue un iPhone 13 128GB de uno de 256GB, que son
    productos distintos y no deben caer en el mismo cluster).
    """
    normalized = normalize_text(text)
    normalized = _CAPACITY_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}", normalized)
    return frozenset(
        token
        for token in normalized.split()
        if len(token) > 1 and token not in STOPWORDS and token not in COLOR_WORDS
    )


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def guess_model(text: str, brand: str | None) -> str | None:
    """Modelo aproximado, para mostrar en la ficha del producto.

    Si el título trae un código de fabricante (`15-fc0235la`) ese es el modelo; si no,
    cae al primer token alfanumérico con dígitos ("iphone 13", "a54", "note 14").
    Aproximación deliberada: sirve para identificar el cluster, no es un dato verificado
    de catálogo.
    """
    codes = extract_model_codes(text)
    if codes:
        # El más largo suele ser el código de producto y no el del chip ("7320u").
        return max(codes, key=len)

    normalized = normalize_text(text)
    if brand:
        normalized = normalized.replace(normalize_text(brand), " ")
    normalized = _CAPACITY_RE.sub(" ", normalized)
    normalized = _SCREEN_RE.sub(" ", normalized)

    words = [w for w in normalized.split() if w not in STOPWORDS and w not in COLOR_WORDS]
    for i, word in enumerate(words):
        if _MODEL_NUM_RE.fullmatch(word) and any(c.isdigit() for c in word):
            prev = words[i - 1] if i > 0 else None
            if prev and prev.isalpha() and len(prev) > 2:
                return f"{prev} {word}"
            return word
    return None
