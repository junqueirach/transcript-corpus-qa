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
| T3 | **Another file** of the same corpus (cited by file and paragraph) | Yes, confidence `high` only |
| T4 | **Outside knowledge** (historical figures, authors, places, published works, institutions) | Only for public, real-world named entities with confidence `high`; always listed for human review |

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

## 6. Language and speaker

The front matter declares `idioma` (the language code; `tcqa classify` detects
the language with a stop-word test and warns when the declaration disagrees)
and `falante_nativo` (is the speaker a native speaker?). For a non-native
speaker, odd grammar belongs to the speaker, not to the ASR: it is never
"corrected". Only mishearings with a single coherent reading may be fixed, as
T2, and logged.

Speaker labels (`**[Name]**` at the start of a turn) come from the registry or
from a generic list (`Interviewer`, `Host`, `Participant 1`, `Audience question`,
`Moderator`, `Unidentified`). A new name is proposed in the log with the literal
self-identification from the audio ("I am …") and enters the registry only after
human approval. Identity is never inferred from the channel.

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
cannot do is change the text silently.

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

## 12. Workflow per file

0. Back up the raw file (mirroring its folder; sequential rename on collision) and
   record its SHA-256.
1. Read the whole file. Confirm language and native-speaker status.
2. Convert the header to front matter.
3. Label speakers.
4. Revise, logging every change with tier, basis and confidence.
5. Mark what cannot be recovered.
6. Run `tcqa classify` to fill the computed fields.
7. Run `tcqa check`. Fix the log or the text until it passes. Never touch the raw.
8. Save; regenerate the human summary and the index.
