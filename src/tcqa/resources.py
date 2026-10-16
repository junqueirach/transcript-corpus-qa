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
    # per term: the spellings a revision may write, and the raw forms a T1 fix may replace
    written: dict[tuple[str, ...], set[tuple[str, ...]]] = field(default_factory=dict)
    replaceable: dict[tuple[str, ...], set[tuple[str, ...]]] = field(default_factory=dict)
    homophones: set[tuple[str, ...]] = field(default_factory=set)        # terms with risco_homofonia: alto
    loaded: bool = False

    def add_term(self, term: str, variants=(), errors=(), homophone: bool = False) -> None:
        ck = tuple(keys_of(term))
        if not ck:
            return
        self.canonical[ck] = term
        written = self.written.setdefault(ck, {ck})
        replaceable = self.replaceable.setdefault(ck, set())
        for variant in variants:
            vk = tuple(keys_of(variant))
            if vk:
                self.variants[vk] = term
                written.add(vk)
                replaceable.add(vk)
        for error in errors:
            ek = tuple(keys_of(error))
            if ek:
                self.variants[ek] = term
                replaceable.add(ek)
        if homophone:
            self.homophones.add(ck)

    def is_homophone(self, term: str) -> bool:
        return tuple(keys_of(term)) in self.homophones

    def canonical_for(self, keys: list[str]) -> str | None:
        return self.variants.get(tuple(keys))

    def is_canonical(self, keys: list[str]) -> bool:
        return tuple(keys) in self.canonical

    def supports_t1(self, term: str, raw: str, revised: str) -> str | None:
        """Why a T1 entry citing ``lexicon:<term>`` is not backed by the lexicon, or None if it is.

        The revised span may carry context words around the term (added to make
        the span unique); those must appear unchanged around the raw form.
        """
        tk = tuple(keys_of(term))
        if tk not in self.written:
            return f"'{term}' is not a term of the lexicon"
        rk, vk = tuple(keys_of(raw)), tuple(keys_of(revised))
        found = False
        for form in self.written[tk]:
            n = len(form)
            for i in range(len(vk) - n + 1):
                if vk[i:i + n] != form:
                    continue
                found = True
                pre, post = vk[:i], vk[i + n:]
                if len(rk) > len(pre) + len(post) and rk[:len(pre)] == pre and rk[len(rk) - len(post):] == post:
                    if rk[len(pre):len(rk) - len(post)] in self.replaceable[tk]:
                        return None
        if not found:
            return f"revised '{revised}' is not '{term}' or one of its variants"
        return f"raw '{raw}' is not a listed error or variant of '{term}'"

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
    lex.loaded = True
    terms = data.get("termos") or data.get("terms") or []
    for entry in terms:
        term = entry.get("termo") or entry.get("term")
        if not term:
            continue
        errors = list(entry.get("erros_previstos") or entry.get("expected_errors") or []) +             list(entry.get("erros_observados") or entry.get("observed_errors") or [])
        lex.add_term(term, entry.get("variantes") or entry.get("variants") or [], errors,
                     homophone=str(entry.get("risco_homofonia") or entry.get("homophone_risk") or "").casefold() in ("alto", "high"))
    return lex


@dataclass
class Speakers:
    labels: set[str] = field(default_factory=set)
    # canonical name -> its known ASR transcription forms (registry 'variantes_de_transcricao')
    name_forms: dict[str, list[str]] = field(default_factory=dict)

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
        sp.name_forms.setdefault(author["nome_canonico"], []).extend(
            author.get("variantes_de_transcricao") or author.get("transcription_variants") or [])
    for channel in data.get("canais") or data.get("channels") or []:
        for person in channel.get("falantes_conhecidos") or channel.get("known_speakers") or []:
            name = person.get("nome") or person.get("name")
            if name:
                sp.labels.add(name)
                sp.name_forms.setdefault(name, []).extend(
                    person.get("variantes_de_transcricao") or person.get("transcription_variants") or [])
    for name in data.get("falantes") or data.get("speakers") or []:
        if isinstance(name, str):
            sp.labels.add(name)
    return sp


def merge_speaker_names(lex: Lexicon, speakers: Speakers) -> Lexicon:
    """Registry names count as lexicon terms: their known ASR forms back a T1 fix
    (``basis: "lexicon:<name>"``) exactly like a lexicon entry's errors."""
    for name, forms in speakers.name_forms.items():
        ck = tuple(keys_of(name))
        if ck in lex.written:
            lex.add_term(lex.canonical[ck], errors=forms)
        else:
            lex.add_term(name, errors=forms)
    return lex
