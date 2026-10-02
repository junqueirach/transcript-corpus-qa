# Contributing

Thanks for looking at this. The tool is small on purpose; the method it
enforces is the valuable part, so changes to rules deserve more discussion than
changes to code.

## Setup

```
git clone https://github.com/junqueirach/transcript-corpus-qa
cd transcript-corpus-qa
python -m pip install -e ".[dev]"
python -m pytest
python examples/run_demo.py --verify
```

Python 3.10+, standard library only at runtime. CI runs the tests on Ubuntu and
Windows with Python 3.10 and 3.12.

## Ground rules

1. **Never invent content.** A fixture is invented text; a correction in a
   fixture has a basis; a marked doubt is better than a guess. The same applies
   to the README: no numbers that a test or the demo did not produce.
2. **Invented text only.** No real transcripts, lexicons, speaker registries,
   prompts or personal file paths in the repository or its history. The
   fixtures use a lecture about a lighthouse that does not exist.
3. **Every check has a fixture that fails without it.** If you add a check,
   add a `fixtures/<case>/` folder with `raw.md`, `revised.md`, `log.jsonl`
   and `expected.json`; the fixture test picks it up automatically.
4. **Rule changes go through `docs/METHOD.md`** in the same pull request, with a
   short "why".
5. Keep code plain: `pathlib`, UTF-8 everywhere, no clever metaprogramming,
   comments where a rule is being enforced (quote the rule).

## Layout

| Path | Content |
|---|---|
| `src/tcqa/` | the package: `checker.py` (C1–C14), `log.py` (validator), `classify.py` (class and flags), `index.py`, `backup.py`, `summarize.py`, `cli.py` |
| `fixtures/` | one folder per case, invented text, with the expected outcome |
| `tests/` | pytest; `test_checker.py` runs every fixture and the random-mutation tests |
| `examples/` | the public demo (`run_demo.py`) |
| `schema/` | JSON Schema for the log and the front matter (documentation; enforced in code) |
| `docs/` | the method and the images |
