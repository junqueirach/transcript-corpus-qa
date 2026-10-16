"""Install (or update) the tcqa agent for Claude Code.

Copies the templates under ``agent/`` to the user's Claude Code folder
(``~/.claude``), replacing ``{TCQA_REPO}`` with this repository's path and
``{CLAUDE_HOME}`` with the Claude Code folder:

    agent/skills/tcqa/SKILL.md        -> ~/.claude/skills/tcqa/SKILL.md      (/tcqa)
    agent/agents/tcqa-reviser.md      -> ~/.claude/agents/tcqa-reviser.md
    agent/agents/tcqa-verifier.md     -> ~/.claude/agents/tcqa-verifier.md

An installed file that differs from what the template would produce is backed up
first (``*.bak-<timestamp>``), so local edits are never lost.

    python agent/install.py [--claude-home PATH] [--check] [--export]

``--check`` only reports whether the installed files match the templates.
``--export`` does the reverse: turns the installed files back into templates
(use it after improving the agent locally, then commit the templates).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FILES = ["skills/tcqa/SKILL.md", "agents/tcqa-reviser.md", "agents/tcqa-verifier.md"]


def render(text: str, claude_home: Path) -> str:
    return text.replace("{TCQA_REPO}", str(REPO)).replace("{CLAUDE_HOME}", str(claude_home))


def unrender(text: str, claude_home: Path) -> str:
    return text.replace(str(claude_home), "{CLAUDE_HOME}").replace(str(REPO), "{TCQA_REPO}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claude-home", default=str(Path.home() / ".claude"))
    ap.add_argument("--check", action="store_true", help="only compare installed files with the templates")
    ap.add_argument("--export", action="store_true", help="copy the installed files back into the templates")
    args = ap.parse_args(argv)
    home = Path(args.claude_home)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    differs = 0
    for rel in FILES:
        template = HERE / rel
        target = home / rel
        if args.export:
            if target.exists():
                template.parent.mkdir(parents=True, exist_ok=True)
                template.write_text(unrender(target.read_text(encoding="utf-8"), home), encoding="utf-8", newline="\n")
                print(f"exported  {target} -> {template}")
            continue
        wanted = render(template.read_text(encoding="utf-8"), home)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == wanted:
            print(f"up to date  {target}")
            continue
        differs += 1
        if args.check:
            print(f"DIFFERS     {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if current is not None:
            shutil.copy2(target, target.with_name(f"{target.name}.bak-{stamp}"))
        target.write_text(wanted, encoding="utf-8", newline="\n")
        print(f"installed   {target}")
    if not args.check and not args.export:
        print("Restart Claude Code if /tcqa or the agents don't appear.")
    return 1 if (args.check and differs) else 0


if __name__ == "__main__":
    sys.exit(main())
