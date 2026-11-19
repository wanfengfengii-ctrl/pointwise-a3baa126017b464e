import sqlite3
from dataclasses import dataclass

from run.manifest import RecordingHeader, decode_row, encode_row
from run.workspace import write_transaction


class RunConflict(ValueError):
    pass


class RunNotFound(LookupError):
    pass


@dataclass(frozen=True)
class RegisteredRun:
    roll_id: str
    header: RecordingHeader
    source_stopped: bool


class RunCatalog:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                roll_id TEXT PRIMARY KEY NOT NULL,
                recording_id TEXT NOT NULL,
                width INTEGER NOT NULL CHECK (width > 0),
                initial_row TEXT NOT NULL,
                source_stopped INTEGER NOT NULL DEFAULT 0 CHECK (source_stopped IN (0, 1))
            )
        ''')

    @staticmethod
    def _registered(row: sqlite3.Row) -> RegisteredRun:
        header = RecordingHeader(row['recording_id'], row['width'], decode_row(row['initial_row']))
        return RegisteredRun(row['roll_id'], header, bool(row['source_stopped']))

    def _find(self, roll_id: str) -> RegisteredRun | None:
        row = self.db.execute('SELECT * FROM runs WHERE roll_id = ?', (roll_id,)).fetchone()
        return None if row is None else self._registered(row)

    def register(self, roll_id: str, header: RecordingHeader) -> RegisteredRun:
        with write_transaction(self.db):
            existing = self._find(roll_id)
            if existing is not None:
                if existing.header != header:
                    raise RunConflict(f'roll {roll_id!r} already has another recording header')
                return existing
            self.db.execute(
                'INSERT INTO runs (roll_id, recording_id, width, initial_row) VALUES (?, ?, ?, ?)',
                (roll_id, header.recording_id, header.width, encode_row(header.initial_row)),
            )
            return RegisteredRun(roll_id, header, False)

    def get(self, roll_id: str) -> RegisteredRun:
        existing = self._find(roll_id)
        if existing is None:
            raise RunNotFound(f'unknown roll {roll_id!r}')
        return existing

    def mark_source_stopped(self, roll_id: str) -> RegisteredRun:
        with write_transaction(self.db):
            self.get(roll_id)
            self.db.execute('UPDATE runs SET source_stopped = 1 WHERE roll_id = ?', (roll_id,))
            return self.get(roll_id)
