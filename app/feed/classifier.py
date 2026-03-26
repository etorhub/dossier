"""Heuristic classifier to detect non-news content (recipes, horoscopes, etc.)."""

# Strong single-term title signals — one match is enough to flag as non_news.
_TITLE_STRONG_SIGNALS: list[str] = [
    # Recipes
    "receta de ",
    "receta para ",
    "recipe for ",
    "recipe:",
    "cómo preparar ",
    "cómo hacer ",
    "how to make ",
    "how to cook ",
    # Horoscopes
    "horóscopo",
    "horoscope",
    "your daily horoscope",
    "tu horóscopo",
    # Sorteos / giveaways
    "sorteo de ",
    "participa en el sorteo",
    "giveaway:",
]

# Groups of signals: if ≥2 from a group appear in title + first 500 chars of
# text → non_news. Keeps false-positive rate low while catching clear cases.
_SIGNAL_GROUPS: list[list[str]] = [
    # Recipes (Spanish/Catalan)
    [
        "ingredientes",
        "cucharada",
        "cucharadita",
        "precalentar",
        "porciones",
        "raciones",
        "tiempo de preparación",
        "tiempo de cocción",
        "minutos de cocción",
        "hornear",
        "mezcla en un bol",
        "añade la harina",
    ],
    # Recipes (English)
    [
        "ingredients",
        "tablespoon",
        "teaspoon",
        "preheat",
        "servings",
        "prep time",
        "cooking time",
        "bake at",
        "degrees fahrenheit",
        "degrees celsius",
    ],
    # Horoscopes
    [
        "aries",
        "tauro",
        "géminis",
        "cáncer",
        "virgo",
        "libra",
        "escorpio",
        "sagitario",
        "capricornio",
        "acuario",
        "piscis",
        "taurus",
        "gemini",
        "cancer",
        "scorpio",
        "sagittarius",
        "capricorn",
        "aquarius",
        "pisces",
    ],
    # Classifieds
    [
        "se vende",
        "en venta",
        "se alquila",
        "precio negociable",
        "referencias personales",
        "contactar por whatsapp",
        "for sale",
        "rental listing",
        "asking price",
    ],
    # Promo / contest
    [
        "bases del concurso",
        "código promocional",
        "oferta exclusiva",
        "descuento especial",
        "participa en nuestro",
        "promo code",
        "exclusive discount",
        "enter to win",
    ],
]


def classify_article(title: str, text: str) -> str:
    """Return 'news' or 'non_news' based on heuristic signals.

    Checks title for strong single-term signals first, then scans
    title + first 500 chars of text for grouped multi-signal patterns.
    A single group needs ≥2 matches to trigger non_news classification.
    """
    title_lower = title.lower() if title else ""
    for phrase in _TITLE_STRONG_SIGNALS:
        if phrase in title_lower:
            return "non_news"

    content = title_lower + " " + (text or "")[:500].lower()
    for group in _SIGNAL_GROUPS:
        hits = sum(1 for signal in group if signal in content)
        if hits >= 2:
            return "non_news"

    return "news"
