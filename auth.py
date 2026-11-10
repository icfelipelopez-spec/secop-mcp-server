"""Validación de API Key Bearer para el transporte MCP."""

import hmac


def api_key_autorizada(authorization: str | None, expected_key: str) -> bool:
    """Valida Authorization: Bearer <key> con comparación en tiempo constante."""
    if not expected_key or not authorization:
        return False

    scheme, separator, supplied_key = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return False

    supplied_key = supplied_key.strip()
    if not supplied_key:
        return False

    return hmac.compare_digest(
        supplied_key.encode("utf-8"), expected_key.encode("utf-8")
    )
