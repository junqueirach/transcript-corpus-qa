# tcqa check report

**FAIL — 11 error(s), 0 warning(s)**

- raw: `raw.md`
- revised: `revised_broken.md`
- log: `log_broken.jsonl`

## Numbers

| what | value |
|---|---|
| raw_words | 165 |
| revised_words | 145 |
| hunks | 8 |
| hesitation_hunks | 3 |
| hesitation_words_removed | 5 |
| explained_hunks | 2 |
| unexplained_hunks | 3 |
| marker_violations | 0 |
| markers_? | 0 |
| markers_?? | 0 |
| accent_or_case_only | 11 |
| log_entries | 4 |
| language_detected | en |
| raw_sha256 | 21d28873e683abb41ae24f7ffb0c02cb8e4968eca41e57652a92e77078b7ead4 |

## Computed quality

- body words: 145; words inside `[[?? ]]`: 0 (0.0 %)
- markers: 0 × `[[? ]]`, 0 × `[[?? ]]`
- computed class: **A**
- apto_rag: True; apto_finetuning: True

## Findings

| severity | check | ¶ | raw | revised | explanation |
|---|---|---|---|---|---|
| error | C1 unlogged difference | 2 | tarbaldo vrzeni | Teobaldo Verzeni | difference without a log entry |
| error | C1 unlogged difference | 2 | storms | seasons | difference without a log entry |
| error | C14 proper-name guard | 2 |  | Teobaldo | capitalised word 'Teobaldo' is absent from the raw text, the log and the lexicon |
| error | C14 proper-name guard | 2 |  | Verzeni | capitalised word 'Verzeni' is absent from the raw text, the log and the lexicon |
| error | C2 log entry without a difference | 2 | tarbaldo vrzeni | [[?? tarbaldo vrzeni ]] | entry c0003: revised span not found in the revised file |
| error | C4 silent deletion | 3 | the light reached twelve miles and the fishermen said it blinked like… |  | silent deletion of 15 consecutive words without a log entry |
| error | C7 front matter and counts |  |  |  | front matter trechos_irrecuperaveis = 1 but the text gives 0 |
| error | C7 front matter and counts |  |  |  | front matter pct_irrecuperavel = 1.25 but the text gives 0.0 |
| error | C7 front matter and counts |  |  |  | front matter palavras_corpo = 160 but the text gives 145 |
| error | C8 quality class |  |  |  | front matter classe_calculada = 'B' but the text gives 'A' |
| error | C8 quality class |  |  |  | class B differs from computed A without override_motivo |

## Review list (risky corrections and suggestions)

Nothing to review: no T3/T4 corrections, no medium/low suggestions, no new speakers.
