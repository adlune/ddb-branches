"""Checks the client and address data typed by the user before it reaches a node."""
import re

RFC_PATTERN = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")  # 3-4 letters, YYMMDD, 3 characters
ZIP_PATTERN = re.compile(r"^[0-9]{5}$")


class ValidationError(Exception):
    """The data typed by the user is not valid. The message says why."""


def _field(data, key, label, max_length, required=True):
    value = (data.get(key) or "").strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > max_length:
        raise ValidationError(f"{label} allows at most {max_length} characters.")
    return value or None  # empty optional fields are saved as NULL


def client(data):
    result = {
        "Name": _field(data, "Name", "Name", 50),
        "PaternalSurname": _field(data, "PaternalSurname", "Paternal surname", 50),
        "MaternalSurname": _field(data, "MaternalSurname", "Maternal surname", 50, required=False),
        "RFC": _field(data, "RFC", "RFC", 13).upper(),
    }
    if not RFC_PATTERN.match(result["RFC"]):
        raise ValidationError("Invalid RFC. Expected 3-4 letters, 6 digits (YYMMDD) and 3 characters.")
    return result


def address(data):
    result = {
        "Street": _field(data, "Street", "Street", 100),
        "Number": _field(data, "Number", "Number", 10),
        "Neighborhood": _field(data, "Neighborhood", "Neighborhood", 100, required=False),
        "State": _field(data, "State", "State", 50),
        "ZIPCode": _field(data, "ZIPCode", "ZIP code", 5),
    }
    if not ZIP_PATTERN.match(result["ZIPCode"]):
        raise ValidationError("The ZIP code must have exactly 5 digits.")
    return result
