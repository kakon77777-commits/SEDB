from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import ProjectConfig


class BackupError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class BackupResult:
    path: Path
    length: int
    sha256: str
    integrity: str
    entity_count: int
    cell_count: int
    wal_checkpoint: tuple[int, int, int]


def create_verified_backup(
    config: ProjectConfig,
    destination: Path,
) -> BackupResult:
    source = config.database_path
    if not source.is_file():
        raise BackupError("database_missing", str(source))
    if destination.exists():
        raise BackupError("backup_exists", str(destination))
    try:
        with sqlite3.connect(source, isolation_level=None) as checkpoint_connection:
            wal_checkpoint = tuple(
                int(value)
                for value in checkpoint_connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
            )
    except sqlite3.Error as exc:
        raise BackupError("database_checkpoint_failure", str(exc)) from exc
    if wal_checkpoint != (0, 0, 0):
        raise BackupError(
            "database_checkpoint_failure",
            f"wal_checkpoint returned {wal_checkpoint}",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb"):
            pass
    except FileExistsError as exc:
        raise BackupError("backup_exists", str(destination)) from exc

    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as source_connection:
            with sqlite3.connect(destination) as backup_connection:
                source_connection.backup(backup_connection)
        with sqlite3.connect(destination) as verification:
            integrity = str(
                verification.execute("PRAGMA integrity_check").fetchone()[0]
            )
            entity_count = int(
                verification.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            )
            cell_count = int(
                verification.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
            )
        if integrity != "ok":
            raise BackupError(
                "backup_integrity_failure",
                f"SQLite integrity_check returned {integrity}",
            )
        data = destination.read_bytes()
        return BackupResult(
            path=destination,
            length=len(data),
            sha256=hashlib.sha256(data).hexdigest().upper(),
            integrity=integrity,
            entity_count=entity_count,
            cell_count=cell_count,
            wal_checkpoint=wal_checkpoint,
        )
    except BackupError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise BackupError("backup_failure", str(exc)) from exc
