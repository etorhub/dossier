"""Strings for translation extraction. Labels from config (languages, styles) are
translated at runtime via _() in templates; this module ensures they are extracted.
Do not import this module — it exists only for pybabel extract.
"""


def _(*args: object) -> str:
    """Placeholder for extraction; do not call."""
    return ""


# Extract config labels (Catalan, Spanish, English, Neutral, Simple)
_("Catalan")
_("Spanish")
_("English")
_("Neutral")
_("Simple")
# Topic labels from config (get_topic_info)
_("General")
_("Politics")
_("Society")
_("Culture")
_("International")
_("Economy")
_("Science")
_("Sports")
_("All")
