#!/usr/bin/env python3
"""Restore an 8search backup created by scripts/backup_data.py.

Stop the application first (for Docker: ``docker compose -f
docker-compose.prod.yml stop web``). The restore writes a safety backup of the
current data before replacing anything, then verifies every restored database.

Usage:
    python scripts/restore_data.py backups/20261118-101500
    python scripts/restore_data.py backups/20261118-101500 --yes
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_data  # noqa: E402

SIDECARS = backup_data.SIDECARS


def verify_backup(source: Path) -> dict:
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"{source} is not a complete 8search backup")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for name, info in manifest.get("databases", {}).items():
        path = source / name
        if not path.is_file():
            raise RuntimeError(f"backup is missing {name}")
        # Check the bytes against the manifest before handing them to SQLite.
        if info.get("sha256") and backup_data.sha256(path) != info["sha256"]:
            raise RuntimeError(f"{name}: checksum does not match the manifest")
        try:
            result = backup_data.integrity_check(path)
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"{name}: not a readable database ({exc})") from exc
        if result != "ok":
            raise RuntimeError(f"{name}: integrity check returned {result!r}")
    return manifest


def restore(source: Path, data_dir: Path, assume_yes: bool) -> None:
    source = Path(source)
    data_dir = Path(data_dir)
    manifest = verify_backup(source)

    if not assume_yes:
        print(
            "Refusing to overwrite live data without --yes.\n"
            f"Stop the app, then run: python scripts/restore_data.py {source} --yes"
        )
        raise SystemExit(2)

    data_dir.mkdir(parents=True, exist_ok=True)
    safety = None
    if backup_data.db_files(data_dir):
        safety = backup_data.create_backup(data_dir, backup_data.BACKUP_DIR)
        print(f"Safety backup of current data: {safety}")

    for name in manifest.get("databases", {}):
        target = data_dir / name
        for suffix in SIDECARS:
            sidecar = Path(str(target) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        shutil.copy2(source / name, target)
        result = backup_data.integrity_check(target)
        if result != "ok":
            raise RuntimeError(f"{name}: restored integrity check returned {result!r}")

    for entry in manifest.get("files", []):
        name = entry.get("name")
        if name and (source / name).is_file():
            shutil.copy2(source / name, data_dir / name)

    print(f"Restored {len(manifest.get('databases', {}))} database(s) into {data_dir}")
    if safety:
        print(f"Previous data is still available at {safety}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="backup directory to restore")
    parser.add_argument("--data-dir", type=Path, default=backup_data.DATA_DIR)
    parser.add_argument("--yes", action="store_true", help="confirm the overwrite")
    args = parser.parse_args(argv)

    try:
        restore(args.backup, args.data_dir, args.yes)
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
