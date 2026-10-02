"""Loaders for the two optional resources: the lexicon and the speaker registry.

Both are JSON. The shapes below are the ones the corpus uses; a smaller shape
with only the fields the checker needs is accepted too (see fixtures).

Lexicon::

    {"termos": [{"termo": "Ponta Serena", "variantes": ["Ponta-Serena"],
                 "erros_previstos": ["ponta sirena"]}]}

Speaker registry::

    {"_rotulos_genericos": ["Entrevistador", ...],
     "autor_principal": {"nome_canonico": "Nome"},
     "canais": [{"canal": "...", "falantes_conhecidos": [{"nome": "Nome"}]}]}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .textnorm import keys_of

GENERIC_LABELS = [
    "Entrevistador", "Apresentador", "Participante 1", "Participante 2",
    "Pergunta da plateia", "Pergunta lida", "Moderador", "Não identificado",
    # English equivalents, so the public examples read naturally
    "Interviewer", "Host", "Participant 1", "Participant 2",
    "Audience question", "Question read aloud", "Moderator", "Unidentified",
]


@dataclass
class Lexicon:
    canonical: dict[tuple[str, ...], str] = field(default_factory=dict)   # keys -> term
    variants: dict[tuple[str, ...], str] = field(default_factory=dict)    # keys -> canonical term

    def canonical_for(self, keys: list[str]) -> str | None:
        return self.variants.get(tuple(keys))

    def is_canonical(self, keys: list[str]) -> bool:
        return tuple(keys) in self.canonical

    def canonical_words(self) -> set[str]:
        out: set[str] = set()
        for ks in self.canonical:
            out.update(ks)
        return out


def load_lexicon(path: Path | str | None) -> Lexicon:
    lex = Lexicon()
    if path is None:
        return lex
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    terms = data.get("termos") or data.get("terms") or []
    for entry in terms:
        term = entry.get("termo") or entry.get("term")
        if not term:
            continue
        ck = tuple(keys_of(term))
        lex.canonical[ck] = term
        for variant in (entry.get("variantes") or entry.get("variants") or []):
            lex.variants[tuple(keys_of(variant))] = term
        for error in (entry.get("erros_previstos") or entry.get("expected_errors") or []):
            lex.variants[tuple(keys_of(error))] = term
    return lex


@dataclass
class Speakers:
    labels: set[str] = field(default_factory=set)

    def allowed(self, label: str) -> bool:
        return label.strip() in self.labels


def load_speakers(path: Path | str | None) -> Speakers:
    sp = Speakers(set(GENERIC_LABELS))
    if path is None:
        return sp
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for label in data.get("_rotulos_genericos") or data.get("generic_labels") or []:
        sp.labels.add(label)
    author = data.get("autor_principal") or data.get("main_author") or {}
    if isinstance(author, dict) and author.get("nome_canonico"):
        sp.labels.add(author["nome_canonico"])
    for channel in data.get("canais") or data.get("channels") or []:
        for person in channel.get("falantes_conhecidos") or channel.get("known_speakers") or []:
            name = person.get("nome") or person.get("name")
            if name:
                sp.labels.add(name)
    for name in data.get("falantes") or data.get("speakers") or []:
        if isinstance(name, str):
            sp.labels.add(name)
    return sp
