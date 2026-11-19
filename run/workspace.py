import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


def open_workspace(path: str | os.PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def write_transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def initialize_workspace(db: sqlite3.Connection) -> None:
    # Each owner defines its schema and uses this module's transaction boundary.
    from archive.disposition import DispositionStore
    from archive.publication import ManifestStore
    from capture.checkpoint import CaptureCheckpoint
    from capture.evidence import EvidenceStore
    from run.catalog import RunCatalog

    with write_transaction(db):
        RunCatalog(db).initialize()
        EvidenceStore(db).initialize()
        CaptureCheckpoint(db).initialize()
        DispositionStore(db).initialize()
        ManifestStore(db).initialize()
