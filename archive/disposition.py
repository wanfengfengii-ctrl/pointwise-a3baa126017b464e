import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from device.frame import FrameOrigin
from run.manifest import decode_row, encode_row


@dataclass(frozen=True)
class Disposition:
    roll_id: str
    sequence: int
    origin: FrameOrigin
    raw_row: tuple[int, ...] | None
    reason: str | None

    @property
    def accepted(self) -> bool:
        return self.raw_row is not None


class DispositionStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS dispositions (
                roll_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                station TEXT NOT NULL,
                source_key TEXT NOT NULL,
                raw_row TEXT,
                reason TEXT,
                PRIMARY KEY (roll_id, sequence),
                FOREIGN KEY (roll_id, sequence) REFERENCES capture_facts (roll_id, sequence),
                CHECK ((raw_row IS NOT NULL AND reason IS NULL)
                    OR (raw_row IS NULL AND reason IS NOT NULL AND length(reason) > 0))
            )
        ''')

    @staticmethod
    def _read(row: sqlite3.Row) -> Disposition:
        raw_row = row['raw_row']
        return Disposition(
            row['roll_id'], row['sequence'], FrameOrigin(row['station'], row['source_key']),
            None if raw_row is None else decode_row(raw_row), row['reason'],
        )

    def record(self, disposition: Disposition) -> None:
        raw_row = None if disposition.raw_row is None else encode_row(disposition.raw_row)
        self.db.execute('''
            INSERT INTO dispositions (roll_id, sequence, station, source_key, raw_row, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            disposition.roll_id, disposition.sequence, disposition.origin.station,
            disposition.origin.source_key, raw_row, disposition.reason,
        ))

    def get(self, roll_id: str, sequence: int) -> Disposition | None:
        row = self.db.execute(
            'SELECT * FROM dispositions WHERE roll_id = ? AND sequence = ?', (roll_id, sequence),
        ).fetchone()
        return None if row is None else self._read(row)

    def read_range(self, roll_id: str, first: int, through: int) -> tuple[Disposition, ...]:
        rows = self.db.execute('''
            SELECT * FROM dispositions WHERE roll_id = ? AND sequence BETWEEN ? AND ?
            ORDER BY sequence
        ''', (roll_id, first, through))
        return tuple(self._read(row) for row in rows)

    def sequences(self, roll_id: str, first: int, through: int) -> Iterator[int]:
        rows = self.db.execute('''
            SELECT sequence FROM dispositions WHERE roll_id = ? AND sequence BETWEEN ? AND ?
            ORDER BY sequence
        ''', (roll_id, first, through))
        return (row['sequence'] for row in rows)
