# Example: one good revision, one broken revision

Everything in `demo/` is invented: a four-minute talk about a lighthouse that
never existed, written to look like raw speech-to-text output.

| File | What it is |
|---|---|
| `demo/raw.md` | The "ASR output": no punctuation, fillers (`um`, `uh`), a repeated word, a `[Music]` tag, a mis-heard place name (`ponta sirena`), a misspelt word (`morter`) and a destroyed personal name (`tarbaldo vrzeni`). |
| `demo/revised_good.md` | A revision that follows the method: punctuation and paragraphs, fillers removed, the place name fixed from the lexicon (T1), `morter → mortar` from context (T2), and the destroyed name **marked** `[[?? tarbaldo vrzeni ]]` instead of guessed. |
| `demo/log_good.jsonl` | The structured log: one line per change, with tier, basis and confidence. |
| `demo/revised_broken.md` | The same revision with three silent violations: the destroyed name replaced by a plausible invented one, `storms → seasons` (a fluent wrong word), and one sentence deleted. The log was not updated. |
| `demo/report_good.md`, `demo/report_broken.md` | What `tcqa check` wrote for each. |
| `demo/lexicon.json`, `demo/speakers.json` | A two-term lexicon and a tiny speaker registry. |

Run it:

```
python examples/run_demo.py
```

Expected: the good revision passes (exit code 0) and the broken one fails
(exit code 1) with findings C1 (unlogged difference), C14 (capitalised word
absent from raw, log and lexicon), C4 (silent deletion), plus the front-matter
counts that no longer match the text (C7, C8). `--verify` additionally checks
that the committed reports are reproduced byte for byte: the checker is
deterministic.
