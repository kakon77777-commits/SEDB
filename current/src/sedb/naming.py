from __future__ import annotations

import re
import unicodedata


_SEPARATORS = re.compile(r"[\s\-./]+")
_UNDERSCORES = re.compile(r"_+")


def normalize_field_key(value: str) -> str:
    """Return the deterministic governance identity token for a field reference."""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = _SEPARATORS.sub("_", text)
    text = _UNDERSCORES.sub("_", text).strip("_")
    if not text:
        raise ValueError("field key cannot normalize to an empty value")
    return text
