"""Fillers and ASR noise that may be removed without an individual log entry.

The lists are deliberately short (decision D9). Words that often carry
meaning (``like``, ``you know``, ``então``, ``tipo``) are NOT here: removing
them needs a log entry.
"""
from __future__ import annotations

from .textnorm import normalize_word

FILLERS: dict[str, set[str]] = {
    "pt": {"eh", "ãh", "ah", "hã", "hum", "hmm", "mm", "né", "uh", "um"},
    "en": {"um", "uh", "er", "ah", "hmm", "mm", "mhm", "uh-huh", "erm"},
}
# Tokens the ASR emits for non-speech. Compared on the word level, so
# '[Música]' is matched by its word 'música'.
NOISE_WORDS = {"música", "music", "aplausos", "applause", "risos", "laughter", "foreign", "__"}


def filler_keys(lang: str | None) -> set[str]:
    """Normalised keys of the fillers for ``lang`` (both lists when unknown)."""
    langs = [lang.split("-")[0].casefold()] if lang else list(FILLERS)
    keys: set[str] = set()
    for code in langs:
        for word in FILLERS.get(code, set()):
            keys.add(normalize_word(word)[1])
    for word in NOISE_WORDS:
        keys.add(normalize_word(word)[1])
    return keys


def is_filler_run(deleted_keys: list[str], before_key: str | None, after_key: str | None, lang: str | None) -> bool:
    """True when every deleted token is a filler, noise, or an immediate repeat.

    ``before_key``/``after_key`` are the surviving raw tokens around the run,
    so that in ``o o o`` -> ``o`` the two deleted ``o`` count as repeats
    whichever copy difflib decided to keep.
    """
    if not deleted_keys:
        return False
    allowed = filler_keys(lang)
    prev = before_key
    for key in deleted_keys:
        if key in allowed or (prev is not None and key == prev) or (after_key is not None and key == after_key):
            prev = key
            continue
        return False
    return True
