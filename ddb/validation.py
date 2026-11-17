"""Validaciones de datos de clientes y direcciones."""
import re

RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")
ZIP_RE = re.compile(r"^[0-9]{5}$")


class ValidationError(Exception):
    """Error en los datos capturados por el usuario."""


def _clean(value):
    value = (value or "").strip()
    return value


def _check(data, field, label, maxlen, required=True):
    value = _clean(data.get(field))
    if required and not value:
        raise ValidationError(f"El campo «{label}» es obligatorio.")
    if len(value) > maxlen:
        raise ValidationError(f"«{label}» admite como máximo {maxlen} caracteres.")
    return value or None


def client(data: dict) -> dict:
    out = {
        "Name": _check(data, "Name", "Nombre", 50),
        "PaternalSurname": _check(data, "PaternalSurname", "Apellido paterno", 50),
        "MaternalSurname": _check(data, "MaternalSurname", "Apellido materno", 50, required=False),
        "RFC": _check(data, "RFC", "RFC", 13).upper(),
    }
    if not RFC_RE.match(out["RFC"]):
        raise ValidationError(
            "RFC inválido. Formato esperado: 3-4 letras, 6 dígitos (AAMMDD) y 3 caracteres de homoclave."
        )
    return out


def address(data: dict) -> dict:
    out = {
        "Street": _check(data, "Street", "Calle", 100),
        "Number": _check(data, "Number", "Número", 10),
        "Neighborhood": _check(data, "Neighborhood", "Colonia", 100, required=False),
        "State": _check(data, "State", "Estado", 50),
        "ZIPCode": _check(data, "ZIPCode", "Código postal", 5),
    }
    if not ZIP_RE.match(out["ZIPCode"]):
        raise ValidationError("El código postal debe tener exactamente 5 dígitos.")
    return out
