"""Parsing helpers for model data ingestion."""


def is_truthy(value: object) -> bool:
    """
    Interpret a value as truthy for Google Sheets inputs.

    Accepts booleans, numeric 1, or case-insensitive "true"/"1" strings.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return False
