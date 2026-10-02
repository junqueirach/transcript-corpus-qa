#!/usr/bin/env python3
"""Run the public demo end to end.

    python examples/run_demo.py            # run both checks, write the reports
    python examples/run_demo.py --verify   # also fail if the reports changed

The good revision must PASS and the deliberately broken one must FAIL; the
script's exit code is 0 only when both happen. All text in examples/demo is
invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    from tcqa.cli import main
except ImportError:  # running from a source checkout without installing
    sys.path.insert(0, str(HERE.parent / "src"))
    from tcqa.cli import main

DEMO = HERE / "demo"


def run(revised: str, log: str, report: str) -> int:
    print(f"\n$ tcqa check raw.md {revised} {log} --lexicon lexicon.json --speakers speakers.json --report {report}")
    return main(["check", str(DEMO / "raw.md"), str(DEMO / revised), str(DEMO / log),
                 "--lexicon", str(DEMO / "lexicon.json"), "--speakers", str(DEMO / "speakers.json"),
                 "--report", str(DEMO / report)])


def main_demo(argv: list[str]) -> int:
    verify = "--verify" in argv
    before = {name: (DEMO / name).read_text(encoding="utf-8") if (DEMO / name).exists() else None
              for name in ("report_good.md", "report_broken.md")}
    good = run("revised_good.md", "log_good.jsonl", "report_good.md")
    broken = run("revised_broken.md", "log_broken.jsonl", "report_broken.md")
    ok = good == 0 and broken == 1
    print(f"\ngood revision: exit {good} (expected 0)   broken revision: exit {broken} (expected 1)")
    if verify:
        for name, old in before.items():
            new = (DEMO / name).read_text(encoding="utf-8")
            if old is not None and old != new:
                print(f"{name} changed since it was committed")
                ok = False
    print("DEMO OK" if ok else "DEMO FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_demo(sys.argv[1:]))
