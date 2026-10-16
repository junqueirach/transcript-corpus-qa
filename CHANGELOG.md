# Changelog

## Unreleased

- `tcqa check` (C11): a T1 entry with `basis: "lexicon:<term>"` is now verified against the lexicon. The term must exist, the revised span must be the term or one of its variants, and the raw span must be one of its listed errors or variants (context words around the term are allowed). Before, any change could be passed off as T1 by citing a lexicon term, which was a false pass. Without `--lexicon` the entry gets a warning ("not verified"). New fixture `bad_t1_not_in_lexicon`.
- Lexicon loader: `erros_observados` / `observed_errors` are accepted alongside `erros_previstos`.
- The speaker registry's known transcription forms of a name (`variantes_de_transcricao`) back a T1 fix like lexicon errors. A T1 fix to a term marked `risco_homofonia: alto` gives a warning and goes on the review list.
- Repeated raw spans: each log entry is matched to the occurrence the alignment puts at its place (no longer always the first); optional `occurrence` field for explicit choice.
- Log: new line type `aceite` (a warning the reviser examined and accepted, with the reason); the report lists it as accepted and it no longer counts. Errors can't be accepted.
- Log: T3 may cite one of the author's works (`basis: "obra: Title, p. 45"` / `cap. 3`).
- Speakers (C10): the labels used in the text must match `falantes`; `autor_principal_participa` must agree with the labels.
- Front matter: `entrevistador`, `entrevistados`, `mencionados`, `autor_principal_participa`, `evidencia_falantes`, `segmentos_nao_conteudo` (ads and other non-content paragraphs, checked), `pct_nao_conteudo` (computed), `contem_dados_pessoais`. The index has the corpus-control columns.
- `tcqa classify --write` normalises `idioma` to the base code and fills `pct_nao_conteudo`.
- A log entry whose `basis` starts with `TODO` (an unfinished draft stub) fails the check (C0).
- Reports, summaries and indexes are written with LF line endings on every platform; console output no longer crashes on a Windows code page.
- New commands: `tcqa lexicon hits|validate|stats|merge|learn`, `tcqa draft-log`, `tcqa review build|apply`, `tcqa export` (RAG JSONL chunks), `tcqa metrics`, `tcqa index summary`.
- `agent/`: the tcqa agent for Claude Code (launcher `/tcqa`, `tcqa-reviser`, `tcqa-verifier`) with an installer.
- METHOD.md: naming speakers from converging evidence, corpus control, non-content segments, personal data, oral forms, book citations, verifier and review queue, draft-log workflow.

## v0.1.0 — 2026-10

First release.

- `tcqa check`: word-level fidelity check of a revised transcript against its raw ASR output and a structured log; checks C1–C14; Markdown report with a review list.
- `tcqa validate-log`: JSON Lines log validator (tiers, confidence, markers, overrides).
- `tcqa classify`: quality class from the share of unrecoverable words, degraded-section rule, computed readiness flags, language detection.
- `tcqa index`: build an index from front matter; audit an existing index.
- `tcqa backup`: mirror raw files into a backup folder with sequential renaming; prints SHA-256.
- `tcqa summarize`: human-readable summary generated from the log.
- 15 invented fixtures, 203 tests including random-mutation tests; public demo with a good and a broken revision.
