#!/usr/bin/env python3
"""Create, verify and restore consistent backups of 8search data.

The application stores its durable state in SQLite databases under ``data/``.
Copying a live SQLite file with ``cp`` can capture a torn write, so this tool
uses SQLite's online backup API, which produces a consistent snapshot while
the app keeps serving requests.

Usage:
    python scripts/backup_data.py                 # back up + verify
    python scripts/backup_data.py --check-only    # integrity-check live DBs
    python scripts/backup_data.py --keep-days 30  # prune old backups
    python scripts/restore_data.py backups/<stamp> --yes

Environment:
    DATA_DIR       default: <repo>/data
    BACKUP_DIR     default: <repo>/backups
    BACKUP_KEEP_DAYS default: 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", ROOT / "backups"))
KEEP_DAYS = max(1, int(os.getenv("BACKUP_KEEP_DAYS", "30")))
SIDECARS = ("-wal", "-shm", "-journal")
SUPPORT_FILES = (".click_secret",)


def db_files(data_dir: Path = DATA_DIR) -> list[Path]:
    return sorted(path for path in data_dir.glob("*.db") if path.is_file())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity_check(path: Path) -> str:
    """Return SQLite's integrity_check result; raises on unreadable files."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
    finally:
        conn.close()


def check_live(data_dir: Path = DATA_DIR) -> dict[str, str]:
    results: dict[str, str] = {}
    for path in db_files(data_dir):
        results[path.name] = integrity_check(path)
    return results


def _copy_support_files(source: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    for name in SUPPORT_FILES:
        path = source / name
        if path.is_file():
            shutil.copy2(path, destination / name)
            copied.append(name)
    return copied


def create_backup(
    data_dir: Path = DATA_DIR,
    backup_dir: Path = BACKUP_DIR,
    keep_days: int = KEEP_DAYS,
) -> Path:
    """Write an atomic, verified backup directory and return its path."""
    data_dir = Path(data_dir)
    backup_dir = Path(backup_dir)
    dbs = db_files(data_dir)
    if not dbs:
        raise RuntimeError(f"no SQLite databases found in {data_dir}")

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    final = backup_dir / stamp
    if final.exists():  # two runs in the same second
        final = backup_dir / f"{stamp}-{os.getpid()}"
    temp = backup_dir / f".tmp-{stamp}-{os.getpid()}"
    temp.mkdir(parents=True, exist_ok=False)

    manifest: dict = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(data_dir),
        "databases": {},
        "files": [],
    }

    try:
        for source in dbs:
            destination = temp / source.name
            source_conn = sqlite3.connect(
                f"file:{source}?mode=ro", uri=True, timeout=30
            )
            destination_conn = sqlite3.connect(destination, timeout=30)
            try:
                source_conn.backup(destination_conn)
            finally:
                destination_conn.close()
                source_conn.close()

            result = integrity_check(destination)
            if result != "ok":
                raise RuntimeError(f"{source.name}: integrity check returned {result!r}")
            manifest["databases"][source.name] = {
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
                "integrity": result,
            }

        for name in _copy_support_files(data_dir, temp):
            path = temp / name
            manifest["files"].append({"name": name, "sha256": sha256(path)})

        (temp / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        # Only publish the backup once every database has passed its check.
        temp.rename(final)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    prune_backups(backup_dir, keep_days)
    return final


def prune_backups(backup_dir: Path = BACKUP_DIR, keep_days: int = KEEP_DAYS) -> list[Path]:
    """Remove complete backups older than keep_days, never the newest one."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    complete = [
        path
        for path in backup_dir.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / "manifest.json").is_file()
    ]
    if len(complete) <= 1:
        return []

    def age_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name)
        except OSError:
            return (0.0, path.name)

    # Never prune the most recent backup, even if its clock is skewed.
    complete.sort(key=age_key)
    newest = complete[-1]

    cutoff = time.time() - keep_days * 86400
    removed: list[Path] = []
    for path in complete:
        if path == newest:
            continue
        try:
            age = path.stat().st_mtime
        except OSError:
            continue
        if age < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--backup-dir", type=Path, default=BACKUP_DIR)
    parser.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify live databases without writing a backup",
    )
    args = parser.parse_args(argv)

    try:
        if args.check_only:
            results = check_live(args.data_dir)
            for name, result in results.items():
                print(f"{name}: {result}")
            return 0 if results and all(value == "ok" for value in results.values()) else 1

        destination = create_backup(args.data_dir, args.backup_dir, args.keep_days)
        size = sum(
            path.stat().st_size for path in destination.iterdir() if path.is_file()
        )
        print(f"Backup written to {destination} ({size} bytes, verified)")
        return 0
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
