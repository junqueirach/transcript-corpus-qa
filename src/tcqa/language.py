"""Language detection with stop words only (no library, no network).

Good enough to tell Portuguese, English, Spanish, French, German and Italian
apart on a few hundred words of speech. When the signal is weak the result is
``None`` so that nobody downstream guesses.
"""
from __future__ import annotations

from .textnorm import WORD_RE, normalize_word

STOPWORDS: dict[str, set[str]] = {
    "pt": {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "que", "e", "é", "não", "um", "uma",
           "para", "com", "no", "na", "nos", "nas", "por", "se", "mais", "como", "mas", "ao", "ele",
           "ela", "isso", "esse", "essa", "este", "esta", "muito", "também", "já", "foi", "são", "está",
           "então", "porque", "quando", "nós", "você", "vocês", "eu", "tem", "tinha", "ser", "sobre",
           "aqui", "gente", "coisa", "pela", "pelo", "até", "aquele", "aquela", "quem", "onde", "só"},
    "en": {"the", "a", "an", "of", "and", "to", "in", "is", "it", "that", "this", "was", "for", "on",
           "with", "as", "are", "be", "by", "at", "or", "from", "have", "has", "not", "but", "they",
           "he", "she", "we", "you", "i", "his", "her", "their", "there", "what", "which", "who",
           "were", "been", "about", "because", "when", "so", "very", "just", "then", "them", "these"},
    "es": {"el", "la", "los", "las", "de", "del", "que", "y", "en", "un", "una", "es", "no", "por",
           "con", "para", "se", "su", "sus", "al", "lo", "como", "más", "pero", "también", "muy",
           "ya", "fue", "son", "está", "entonces", "porque", "cuando", "nosotros", "usted", "yo",
           "tiene", "ser", "sobre", "aquí", "cosa", "hasta", "ese", "esa", "este", "esta", "qué"},
    "fr": {"le", "la", "les", "de", "des", "du", "que", "et", "en", "un", "une", "est", "ne", "pas",
           "pour", "avec", "dans", "sur", "se", "ce", "cette", "ces", "il", "elle", "nous", "vous",
           "ils", "je", "qui", "au", "aux", "plus", "mais", "aussi", "très", "été", "sont", "donc",
           "parce", "quand", "a", "y", "ça", "chose", "là", "où", "tout"},
    "de": {"der", "die", "das", "und", "ist", "ein", "eine", "nicht", "zu", "in", "den", "dem", "des",
           "mit", "auf", "für", "von", "sich", "auch", "es", "sie", "er", "wir", "ich", "ihr", "aber",
           "dass", "wenn", "noch", "sehr", "schon", "war", "sind", "dann", "weil", "wie", "was", "wer",
           "hier", "oder", "nur", "haben", "sein", "über", "diese", "dieser", "man"},
    "it": {"il", "la", "lo", "gli", "le", "di", "del", "della", "che", "e", "è", "non", "un", "una",
           "per", "con", "in", "nel", "nella", "si", "più", "come", "ma", "anche", "molto", "già",
           "stato", "sono", "allora", "perché", "quando", "noi", "voi", "io", "ha", "hanno", "essere",
           "su", "qui", "cosa", "fino", "quello", "quella", "questo", "questa", "chi", "dove", "solo"},
}


def detect_language(text: str, min_words: int = 30) -> tuple[str | None, float]:
    """Return (language code or None, confidence 0..1).

    Confidence is the share of words that are stop words of the winning
    language minus the runner-up's share, so a tie means ~0.
    """
    words = [normalize_word(w)[0] for w in WORD_RE.findall(text)]
    if len(words) < min_words:
        return None, 0.0
    total = len(words)
    scores = {lang: sum(1 for w in words if w in stops) / total for lang, stops in STOPWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, second = ranked[0], ranked[1]
    margin = best[1] - second[1]
    if best[1] < 0.08 or margin < 0.03:
        return None, round(margin, 3)
    return best[0], round(margin, 3)


def language_matches(declared: str | None, detected: str | None) -> bool:
    """'pt-BR' matches 'pt'; None never matches."""
    if not declared or not detected:
        return False
    return declared.casefold().split("-")[0] == detected.casefold()
