"""Encoding rules (ARCHITECTURE 3.8): explicit UTF-8, NFC names, and a mojibake detector."""

from __future__ import annotations

import re
import unicodedata

# Text that was UTF-8 but got decoded as cp1252/latin-1 shows these lead characters followed by a continuation char.
_MOJIBAKE = re.compile(r"(?:Ã[\u0080-¿]|Â[\u0080-¿]|â€[\u0090-¿™œ]|Ä[\u0080-¿]|Å[\u0080-¿])")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def looks_like_mojibake(text: str) -> bool:
    """True for text that re-decodes from cp1252 into valid UTF-8 (for example 'Ã©' for 'é')."""
    if not _MOJIBAKE.search(text):
        return False
    try:
        text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    return True


def decode_utf8(raw: bytes) -> str:
    """Always UTF-8, never the locale (C10: a Windows console crashed on non-ASCII names)."""
    return raw.decode("utf-8", errors="strict")
