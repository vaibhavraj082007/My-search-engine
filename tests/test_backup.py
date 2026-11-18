"""Backup and restore tooling for durable SQLite data."""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backup_data  # noqa: E402
import restore_data  # noqa: E402


def make_db(path: Path, value: str = "first") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE records (value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (value) VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def read_value(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM records").fetchone()[0]
    finally:
        conn.close()


def test_backup_is_consistent_verified_and_restorable(tmp_path, monkeypatch):
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    data.mkdir()
    make_db(data / "users.db", "original")
    (data / ".click_secret").write_text("keep-me", encoding="utf-8")

    destination = backup_data.create_backup(data, backups, keep_days=30)

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["databases"]["users.db"]["integrity"] == "ok"
    assert (destination / ".click_secret").read_text(encoding="utf-8") == "keep-me"

    # Change the live database, then restore the snapshot.
    conn = sqlite3.connect(data / "users.db")
    conn.execute("UPDATE records SET value = 'changed'")
    conn.commit()
    conn.close()
    assert read_value(data / "users.db") == "changed"

    monkeypatch.setattr(backup_data, "BACKUP_DIR", backups)
    restore_data.restore(destination, data, assume_yes=True)
    assert read_value(data / "users.db") == "original"
    assert backup_data.integrity_check(data / "users.db") == "ok"


def test_restore_refuses_without_confirmation(tmp_path):
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    data.mkdir()
    make_db(data / "users.db")
    destination = backup_data.create_backup(data, backups, keep_days=30)

    try:
        restore_data.restore(destination, data, assume_yes=False)
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - the guard must always fire
        raise AssertionError("restore should require --yes")


def test_restore_rejects_a_tampered_backup(tmp_path):
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    data.mkdir()
    make_db(data / "users.db")
    destination = backup_data.create_backup(data, backups, keep_days=30)

    (destination / "users.db").write_bytes(b"not a database")

    try:
        restore_data.verify_backup(destination)
    except RuntimeError:
        pass
    else:  # pragma: no cover - corruption must be detected
        raise AssertionError("tampered backup should fail verification")


def test_prune_keeps_the_newest_backup(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    old = backups / "old"
    new = backups / "new"
    for path in (old, new):
        path.mkdir()
        (path / "manifest.json").write_text("{}", encoding="utf-8")
    old_time = time.time() - 60 * 86400
    os.utime(old, (old_time, old_time))

    backup_data.prune_backups(backups, keep_days=30)
    assert new.is_dir()
    assert not old.exists()


def test_check_only_reports_every_database(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    make_db(data / "users.db")
    make_db(data / "clicks.db")

    results = backup_data.check_live(data)
    assert results == {"clicks.db": "ok", "users.db": "ok"}
