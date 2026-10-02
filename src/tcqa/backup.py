"""``tcqa backup``: copy raw files into a backup folder before they are
overwritten by a revision (decision D8).

The copy keeps the file's sub-folder relative to ``--root``. If a file with the
same name already exists in the backup folder, the new copy gets a sequential
suffix (``name_001.md``, ``name_002.md``, ...). Nothing is ever overwritten.
The SHA-256 of each copied file is printed so it can go into ``raw_sha256``.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def next_free_name(folder: Path, name: str) -> Path:
    """``name.md`` if free, else ``name_001.md``, ``name_002.md``, ..."""
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = folder / f"{stem}_{n:03d}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def backup_file(source: Path, root: Path, backup_dir: Path, dry_run: bool = False) -> tuple[Path, str]:
    """Copy ``source`` under ``backup_dir`` mirroring its path relative to
    ``root``. Returns (destination, sha256)."""
    source = source.resolve()
    root = root.resolve()
    try:
        relative = source.relative_to(root)
    except ValueError:
        relative = Path(source.name)
    target_dir = backup_dir / relative.parent
    destination = next_free_name(target_dir, relative.name)
    digest = sha256_file(source)
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return destination, digest


def cmd_backup(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    backup_dir = Path(args.backup_dir)
    status = 0
    for name in args.files:
        source = Path(name)
        if not source.is_file():
            print(f"skip (not a file): {name}")
            status = 1
            continue
        destination, digest = backup_file(source, root, backup_dir, dry_run=args.dry_run)
        verb = "would copy" if args.dry_run else "copied"
        print(f"{digest}  {verb} {source.name} -> {destination}")
    return status


def add_backup_parser(sub) -> None:
    p = sub.add_parser("backup", help="copy raw files to a backup folder (mirrors sub-folders, never overwrites)")
    p.add_argument("files", nargs="+", help="raw transcript files to back up")
    p.add_argument("--backup-dir", required=True, help="where the copies go")
    p.add_argument("--root", help="corpus root; the file's path relative to it is mirrored (default: current folder)")
    p.add_argument("--dry-run", action="store_true", help="show what would be copied")
    p.set_defaults(func=cmd_backup)
