# The method: revising speech-to-text transcripts without inventing anything

This document describes the revision method that `tcqa` enforces. It is written
for people who prepare spoken-word corpora (talks, podcasts, interviews) for
retrieval (RAG) or fine-tuning, and who care that the final text contains only
what the speaker said. All examples below are invented.

## 1. The one principle

**Traceability first, fluency second.** A marked doubt is better than a
reconstructed guess. A fluent transcript that quietly contains words the speaker
never said is worse than a rough one that says "I could not recover this".

Everything else in the method follows from that sentence:

- every change that is not purely mechanical is written to a log, with the
  original span, the new span, how it was justified and how sure the reviser was;
- unclear passages are **marked, not filled in**, and the original words stay
  inside the mark;
- a program (`tcqa check`) compares raw and revised text word by word and refuses
  any difference that the log does not explain.

## 2. Files and roles

| File | Role |
|---|---|
| `raw.md` | The transcript as produced by the ASR system. Never edited. Its SHA-256 is recorded. |
| `revised.md` | The revised transcript with YAML front matter. |
| `revised.log.jsonl` | One JSON object per line: a header, then one entry per change. |
| `lexicon.json` (optional) | Domain terms with their known ASR mis-spellings. |
| `speakers.json` (optional) | Registry of known speaker names plus generic labels. |

## 3. Markers

Three forms. In all of them the original text stays intact inside the brackets.

```
[[? original text that is probably wrong ]]
[[?? original text that cannot be recovered ]]
[[? original text ⟶ suggestion: proposed reading ]]
```

- `[[? ]]`: suspected error, but the general sense is still readable.
- `[[?? ]]`: no recoverable sense; destroyed names; lost audio.
- `⟶ suggestion:` (arrow U+27F6) may follow the original in either form. The
  checker compares the text *before* the arrow with the raw file.
- Markers do not nest and do not cross paragraph boundaries.
- Nothing inside a marker is edited — not punctuation, not case, not fillers.

A reviser may add a note after a paragraph, on its own line, starting with
`> **[review note]**` (or `> **[nota de revisão]**`). Notes are not transcript text; the checker ignores them, and they attach to the paragraph before them.

## 4. Correction tiers and confidence

Every logged change carries a **tier** (where the justification comes from) and a
**confidence** (`high`, `medium`, `low`).

| Tier | Justification comes from | Allowed in the text? |
|---|---|---|
| T1 | Nothing beyond the surface: punctuation, paragraphs, case, listed fillers, ASR noise tags, exact lexicon variants | Yes |
| T2 | The surrounding text of the **same file**; only one coherent reading exists | Yes, confidence `high` only |
| T3 | **Another file** of the same corpus (`crossfile: other.md ¶12`), or one of the **author's works** (`obra: Title, p. 45` / `cap. 3`); a work confirms spelling and terms, never the speaker's wording | Yes, confidence `high` only |
| T4 | **Outside knowledge** (historical figures, authors, places, published works, institutions) | Only for public, real-world named entities with confidence `high`; always listed for human review |

A T1 entry citing the lexicon (`basis: "lexicon:<term>"`) must be backed by it: the term exists,
the revised words are the term or one of its variants, and the raw words are one of its listed errors
or variants (the known transcription forms of a registered speaker's name count too). A lexicon term
written from an ASR form that is **not** listed is T2 with context, and the form is proposed for the
lexicon after the run. Terms marked `risco_homofonia: alto` collide with common words: a T1 fix to
them is accepted but goes to human review.

`medium` and `low` never change the text. They become a marker with a suggestion.
Dates, numbers, arithmetic reconstructions ("six years after 1991 is 1997") and
any name that is neither in the lexicon nor a verifiable public entity are always
markers.

The T2 test, in one sentence: *does the sentence, as it stands, admit only one
coherent reading, and can that reading be rebuilt from the neighbouring words?*

**Beware the fluent error.** On degraded audio, ASR systems produce normal words
that do not belong to the context. They do not look like errors. Judge by the
meaning of the passage, not by the grammaticality of the sentence. A fluent wrong
word swapped silently is exactly what the checker exists to catch.

Invented example (Portuguese, from a made-up lecture about a lighthouse): raw
`as pedras foram assentadas sem agarmassa` → revised `as pedras foram assentadas
sem argamassa`. This is T2: "agarmassa" does not exist and the frame "assentadas
sem ___" admits one reading. By contrast, a destroyed name in `o farol foi
desenhado pelo engenheiro Tarbaldo Vrzeni` becomes `[[?? Tarbaldo Vrzeni ]]`: no
context determines it, so filling it in would be fabrication.

## 5. Fillers, noise and mechanical changes

Mechanical changes (whitespace, punctuation, case, paragraph breaks) are allowed
without individual log entries; the log may record them as one bulk entry.

Fillers that may be removed without an individual entry are listed per language
(e.g. English `um`, `uh`, `er`, `ah`, `hmm`; Portuguese `eh`, `ãh`, `hã`, `hum`,
filler `né`), plus immediate repetitions (`the the`) and ASR noise tags
(`[Music]`, `[Applause]`, `foreign`). Words that often carry meaning (`like`,
`you know`, `so`, `well`, `então`, `tipo`) are **not** on the list: removing them
needs a log entry.

Oral forms (`tá`, `pra`, `gonna`) are speech, not errors: a corpus may decide to keep
them as spoken (the default) or to standardise them, and writes that decision in its
corpus guide. Short interjections of the other speaker (`uhum`, `sim`, `right`) stay
where they occur, in parentheses. Platform masks such as YouTube's `[ __ ]` stay as
they are.

**Non-content speech** (ads, sponsor reads, jingles, fixed openings) is still speech: it is
revised like the rest and never deleted, but its paragraphs are tagged in the front matter
(`segmentos_nao_conteudo: ["1:anuncio", "29-30:anuncio"]`, types `anuncio`, `vinheta`,
`abertura`, `encerramento`, `outro`). `tcqa classify --write` computes their share of words
(`pct_nao_conteudo`) and exporters leave them out by default.

**Personal data** read on air (e-mail, phone, address) is kept as heard by default and the
file is flagged `contem_dados_pessoais: true`, so a corpus builder can filter or mask it.

## 6. Language and speaker

The front matter declares `idioma` (the language code; `tcqa classify` detects
the language with a stop-word test and warns when the declaration disagrees)
and `falante_nativo` (is the speaker a native speaker?). For a non-native
speaker, odd grammar belongs to the speaker, not to the ASR: it is never
"corrected". Only mishearings with a single coherent reading may be fixed, as
T2, and logged.

Speaker labels (`**[Name]**` at the start of a turn) come from the registry or
from a generic list (`Interviewer`, `Host`, `Participant 1`, `Audience question`,
`Moderator`, `Unidentified`).

**Naming people.** A speaker is named when the evidence proves who it is: at least
**two independent sources agree** and none contradicts them. Sources: the recording's
metadata (`Autor:` in the raw header, the file or video title), the channel (its usual
host), and the text itself — the host's greeting or introduction ("our guest today,
Alfredo…"), a self-identification ("I am …"), the person spelling their name, names used in
direct address or thanks, authorship clues ("in my book …" for a known work of that
person), biography clues. Third-person mentions rule a person *out* as the speaker.
The channel alone never decides identity. When the evidence is sufficient, naming is
mandatory (a generic label would discard known information); when it isn't, a generic
label is used. A name not yet in the registry is proposed in the log (`falante_novo`
with the quotes) and enters the registry after human approval.

The front matter records who took part and who was only talked about: `falantes`
(exactly the labels used in the text), `entrevistador`, `entrevistados`, `mencionados`,
`evidencia_falantes`, and `autor_principal_participa` — whether the corpus's main
author speaks in this file. The checker verifies that `falantes` matches the labels and
that the participation flag agrees with them.

## 7. Quality class, computed then judged

After revision, the tool counts the body words and the words inside markers and
computes the **share of body words inside `[[?? ]]`**:

| Class | Share of words inside `[[?? ]]` |
|---|---|
| A | 0 % |
| B | up to 2 % |
| C | above 2 % |

It is a share of **words**, not a count of markers, so one marker hiding a whole
paragraph weighs as much as it should, and the measure scales from a 15-minute
talk to a 3-hour seminar.

*Section rule:* if one contiguous run holding at most 25 % of the words contains at
least 75 % of the unrecoverable words, and the rest of the file alone is within
2 %, the file is class B and the degraded section is recorded instead of
downgrading the whole file.

*Human override:* the reviser may move the class by **one step** (A↔B, B↔C) with a
one-sentence reason in the front matter. Two steps are never accepted.

## 8. Computed readiness flags

`apto_finetuning` (fit for fine-tuning) and `apto_rag` (fit for retrieval) are
computed, never typed:

- `apto_finetuning = false` if the class is C, if the file is derived (a
  translation), or if its language is outside the configured scope
  (`--finetune-languages`);
- `apto_rag = false` only when the file is unreadable (more than half of its
  words unrecoverable).

## 9. Translations

A translation is a derived file (`derivado_de` names the source file), never a
replacement. Passages inside `[[?? ]]` stay in the source language. The
translation keeps the same number of paragraphs and the same markers, in the same
order, as its source. Translations are not fine-tuning material by default.

## 10. What the checker proves — and what it does not

`tcqa check raw.md revised.md revised.log.jsonl` proves that **every difference
between raw and revised is either mechanical, a listed filler, a marker wrapping
the original, or explained by a log entry with a tier and a basis**, and that the
front matter numbers (counts, class, flags) match what the text actually contains.

It does **not** judge whether a correction is linguistically right, does not
listen to audio, does not call any model, and runs offline and deterministically.
A reviser can still log a wrong correction with `high` confidence; what they
cannot do is change the text silently. That is why the agent workflow adds an
independent **verifier** that re-judges every T2/T3/T4 correction and speaker label and
may only move toward caution (a correction it can't confirm becomes a marker with a
suggestion), and a **human review queue** for what remains.

A warning the reviser examined and accepts is recorded in the log
(`{"type": "aceite", "code": "C10", "motivo": "…"}`); the report lists it as accepted and
it no longer counts. Errors can never be accepted.

## 11. Front-matter fields

The field names are Portuguese because the method was born on a Portuguese
corpus; the checker enforces them as written. Full list with types in
`schema/frontmatter.schema.json`; the ones the checker verifies:

| Field | Meaning | Who writes it |
|---|---|---|
| `idioma`, `falante_nativo`, `derivado_de` | language, native speaker, source file of a translation | reviser (language confirmed by `classify`) |
| `raw_sha256` | hash of the raw file | `tcqa backup` / `tcqa hash` |
| `palavras_corpo`, `trechos_incertos`, `trechos_irrecuperaveis`, `pct_irrecuperavel`, `secao_degradada` | counts and the share of unrecoverable words | `tcqa classify --write` |
| `classe_calculada` | class from the numbers | `tcqa classify --write` |
| `classe_qualidade`, `override_motivo` | final class; reason when it differs by one step | reviser |
| `apto_rag`, `apto_finetuning` | readiness flags | `tcqa classify --write` |
| `termos_corrigidos` | T1 lexicon fixes in the log | `tcqa classify --write` |
| `falantes`, `entrevistador`, `entrevistados`, `mencionados`, `autor_principal_participa`, `evidencia_falantes` | who speaks, in which role, who is only mentioned, does the main author speak, the evidence | reviser (checked against the labels) |
| `segmentos_nao_conteudo`, `pct_nao_conteudo` | ads and other non-content paragraphs; their share of words | reviser; `tcqa classify --write` |
| `contem_dados_pessoais` | personal contact data read on air is in the text | reviser |

## 12. Workflow per file

0. Back up the raw file (mirroring its folder; sequential rename on collision) and
   record its SHA-256.
1. Read the whole file and the lexicon entries that occur in it
   (`tcqa lexicon hits raw.md --lexicon …`). Confirm language and native-speaker status.
2. Convert the header to front matter.
3. Identify and label speakers (see §6); record roles and participation.
4. Revise; mark what cannot be recovered; tag non-content segments.
5. Write the log: `tcqa draft-log raw.md revised.md` writes the header, bulk counts and one
   stub per difference and marker; complete every stub with tier, basis and confidence
   (a stub left with `basis: TODO…` fails the check).
6. Run `tcqa classify --write` to fill the computed fields.
7. Run `tcqa check`. Fix the log or the text until it passes. Never touch the raw.
8. Save; regenerate the human summary and the index.

Across a corpus, the agent workflow adds: one speaker pass per channel before revising,
a verifier per file, the lexicon learning from finished logs (`tcqa lexicon learn`: new ASR
forms of known terms automatically, new terms only after approval), one grouped human
review queue per run (`tcqa review build / apply`), a corpus index and dashboard
(`tcqa index build / summary`) and a RAG export (`tcqa export`).
