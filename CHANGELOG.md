# Changelog

## Unreleased

- `tcqa check` (C11): a T1 entry with `basis: "lexicon:<term>"` is now verified against the lexicon. The term must exist, the revised span must be the term or one of its variants, and the raw span must be one of its listed errors or variants (context words around the term are allowed). Before, any change could be passed off as T1 by citing a lexicon term, which was a false pass. Without `--lexicon` the entry gets a warning ("not verified"). New fixture `bad_t1_not_in_lexicon`.
- Lexicon loader: `erros_observados` / `observed_errors` are accepted alongside `erros_previstos`.

## v0.1.0 — 2026-10

First release.

- `tcqa check`: word-level fidelity check of a revised transcript against its raw ASR output and a structured log; checks C1–C14; Markdown report with a review list.
- `tcqa validate-log`: JSON Lines log validator (tiers, confidence, markers, overrides).
- `tcqa classify`: quality class from the share of unrecoverable words, degraded-section rule, computed readiness flags, language detection.
- `tcqa index`: build an index from front matter; audit an existing index.
- `tcqa backup`: mirror raw files into a backup folder with sequential renaming; prints SHA-256.
- `tcqa summarize`: human-readable summary generated from the log.
- 15 invented fixtures, 203 tests including random-mutation tests; public demo with a good and a broken revision.
