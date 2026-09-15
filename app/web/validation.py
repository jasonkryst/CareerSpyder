from pydantic import ValidationError


def fmt_validation_error(exc: ValidationError) -> str:
    """Return a user-facing string for a pydantic ValidationError.

    Each error is rendered as "field: message" (or just "message" when
    there is no meaningful field path). Pydantic's internal type codes,
    doc URLs, and Python type names are stripped.
    """
    parts = []
    for err in exc.errors():
        loc_parts = [str(p) for p in err["loc"] if p not in ("__root__", 0)]
        field = ".".join(loc_parts) if loc_parts else ""
        msg = err["msg"]
        parts.append(f"{field}: {msg}" if field else msg)
    return "; ".join(parts)
