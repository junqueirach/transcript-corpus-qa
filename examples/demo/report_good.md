# tcqa check report

**PASS — 0 error(s), 0 warning(s)**

- raw: `raw.md`
- revised: `revised_good.md`
- log: `log_good.jsonl`

## Numbers

| what | value |
|---|---|
| raw_words | 165 |
| revised_words | 160 |
| hunks | 5 |
| hesitation_hunks | 3 |
| hesitation_words_removed | 5 |
| explained_hunks | 2 |
| unexplained_hunks | 0 |
| marker_violations | 0 |
| markers_? | 0 |
| markers_?? | 1 |
| accent_or_case_only | 12 |
| log_entries | 4 |
| language_detected | en |
| raw_sha256 | 21d28873e683abb41ae24f7ffb0c02cb8e4968eca41e57652a92e77078b7ead4 |

## Computed quality

- body words: 160; words inside `[[?? ]]`: 2 (1.25 %)
- markers: 0 × `[[? ]]`, 1 × `[[?? ]]`
- computed class: **B**
- apto_rag: True; apto_finetuning: True

## Findings

None. Every difference between raw and revised is mechanical, a listed filler, a marker wrapping the original, or explained by the log.

## Review list (risky corrections and suggestions)

Nothing to review: no T3/T4 corrections, no medium/low suggestions, no new speakers.
