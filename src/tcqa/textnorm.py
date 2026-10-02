"""Text model: paragraphs, speaker labels, review notes, markers and tokens.

Everything the checker and the classifier know about a transcript body comes
from :func:`analyze`. It never changes the text; it only describes it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .frontmatter import split_document

ARROW = "⟶"
MARKER_RE = re.compile(r"\[\[(\?\??)\s(.*?)\s\]\]", re.S)
SUGGESTION_RE = re.compile(r"\s" + ARROW + r"\s(?:sugest[aã]o|suggestion):\s")
SPEAKER_RE = re.compile(r"^\*\*\[([^\]\n]+)\]\*\*[ \t]*")
NOTE_PREFIXES = ("> **[nota de revisão]**", "> **[review note]**")
TIMESTAMP_RE = re.compile(r"\[t=\d{1,2}(?::\d{2}){1,2}(?:\.\d+)?\]")
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


@dataclass
class Token:
    text: str
    norm: str
    key: str
    para: int
    start: int
    end: int
    marker: str | None = None  # '?' / '??' when inside a marker's original text


@dataclass
class Marker:
    kind: str
    original: str
    suggestion: str | None
    para: int
    start: int
    end: int


@dataclass
class Paragraph:
    index: int
    text: str
    kind: str  # 'text' | 'note'
    speaker: str | None
    start: int
    end: int


@dataclass
class Document:
    frontmatter: dict | None
    header_kind: str
    body: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    tokens: list[Token] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    speakers: list[tuple[int, str]] = field(default_factory=list)  # (para, label)
    timestamps: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    # ---- convenience -------------------------------------------------
    @property
    def text_paragraphs(self) -> list[Paragraph]:
        return [p for p in self.paragraphs if p.kind == "text"]

    def words(self) -> list[Token]:
        return self.tokens

    def words_in_markers(self, kind: str) -> int:
        return sum(1 for t in self.tokens if t.marker == kind)

    def count_markers(self, kind: str) -> int:
        return sum(1 for m in self.markers if m.kind == kind)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def normalize_word(text: str) -> tuple[str, str]:
    """Return (norm, key): NFC+casefold, and the same with accents removed."""
    norm = nfc(text).casefold().replace("’", "'")
    return norm, strip_accents(norm)


def split_paragraphs(body: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of paragraphs separated by blank lines."""
    spans, start = [], None
    pos = 0
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and start is None:
            start = pos
        if not stripped and start is not None:
            spans.append((start, pos))
            start = None
        pos += len(line)
    if start is not None:
        spans.append((start, len(body)))
    return spans


def tokenize_span(text: str, base: int, para: int, marker: str | None) -> list[Token]:
    out = []
    for m in WORD_RE.finditer(text):
        norm, key = normalize_word(m.group(0))
        out.append(Token(m.group(0), norm, key, para, base + m.start(), base + m.end(), marker))
    return out


def analyze_body(body: str) -> Document:
    body = nfc(body)
    doc = Document(frontmatter=None, header_kind="none", body=body)
    for m in MARKER_RE.finditer(body):
        if "\n\n" in m.group(2):
            doc.problems.append("a marker crosses a paragraph boundary (blank line inside [[ ]])")
    index = 0
    for start, end in split_paragraphs(body):
        raw_text = body[start:end]
        text = raw_text.strip()
        if text.startswith(NOTE_PREFIXES):
            # a note belongs to the paragraph it follows; it gets no number of its own
            doc.paragraphs.append(Paragraph(index, text, "note", None, start, end))
            continue
        if text.startswith(">"):
            doc.problems.append(f"paragraph {index + 1}: quote block that is not a review note")
        opened, closed = text.count("[[?"), text.count("]]")
        if opened != closed:
            doc.problems.append(f"paragraph {index + 1}: unbalanced marker brackets ({opened} '[[?' vs {closed} ']]')")
        index += 1
        speaker = None
        offset = start + (len(raw_text) - len(raw_text.lstrip()))
        m = SPEAKER_RE.match(body[offset:end])
        if m:
            speaker = m.group(1).strip()
            doc.speakers.append((index, speaker))
            offset += m.end()
        doc.paragraphs.append(Paragraph(index, text, "text", speaker, start, end))
        _tokenize_paragraph(doc, index, offset, end)
    return doc


def _tokenize_paragraph(doc: Document, para: int, start: int, end: int) -> None:
    body = doc.body
    pos = start
    for m in MARKER_RE.finditer(body, start, end):
        kind, inner = m.group(1), m.group(2)
        # text before the marker
        doc.tokens.extend(_plain_tokens(body, pos, m.start(), para))
        parts = SUGGESTION_RE.split(inner, maxsplit=1)
        original = parts[0]
        suggestion = parts[1] if len(parts) == 2 else None
        inner_start = m.start(2)
        doc.markers.append(Marker(kind, original, suggestion, para, m.start(), m.end()))
        doc.tokens.extend(_plain_tokens(body, inner_start, inner_start + len(original), para, kind))
        pos = m.end()
    doc.tokens.extend(_plain_tokens(body, pos, end, para))


def _plain_tokens(body: str, start: int, end: int, para: int, marker: str | None = None) -> list[Token]:
    """Tokenize body[start:end], skipping timestamps like [t=01:07]."""
    out, pos = [], start
    segment = body[start:end]
    for ts in TIMESTAMP_RE.finditer(segment):
        out.extend(tokenize_span(body[pos:start + ts.start()], pos, para, marker))
        pos = start + ts.end()
    out.extend(tokenize_span(body[pos:end], pos, para, marker))
    return out


def analyze(text: str) -> Document:
    """Analyze a full document (front matter or legacy header + body)."""
    fm, body, kind = split_document(nfc(text))
    doc = analyze_body(body)
    doc.frontmatter = fm
    doc.header_kind = kind
    doc.timestamps = TIMESTAMP_RE.findall(body)
    return doc


def find_subsequence(haystack: list[str], needle: list[str], start: int = 0) -> list[int]:
    """All start indexes where ``needle`` occurs inside ``haystack``."""
    if not needle:
        return []
    n, hits = len(needle), []
    first = needle[0]
    for i in range(start, len(haystack) - n + 1):
        if haystack[i] == first and haystack[i:i + n] == needle:
            hits.append(i)
    return hits


def keys_of(text: str) -> list[str]:
    """Alignment keys of a free text span (markers' brackets ignored)."""
    text = nfc(text)
    # drop suggestion part and marker syntax so a log span matches the token stream
    def _inner(m: re.Match) -> str:
        parts = SUGGESTION_RE.split(m.group(2), maxsplit=1)
        return " " + parts[0] + " "
    text = MARKER_RE.sub(_inner, text)
    text = SPEAKER_RE.sub("", text)
    text = TIMESTAMP_RE.sub(" ", text)
    return [normalize_word(w)[1] for w in WORD_RE.findall(text)]
