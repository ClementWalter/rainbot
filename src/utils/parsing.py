"""Parsing helpers for model data ingestion."""


def is_truthy(value: object) -> bool:
    """
    Interpret a value as truthy for Google Sheets inputs.

    Accepts booleans, numeric 1, or common truthy strings (English/French).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in ("true", "1", "yes", "y", "oui", "vrai")
    return False
