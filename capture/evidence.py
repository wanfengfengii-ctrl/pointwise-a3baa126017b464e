import json
import sqlite3
from dataclasses import dataclass

from device.frame import FrameOrigin, SourceFrame
from run.manifest import decode_row, encode_row


class ReplayConflict(ValueError):
    pass


@dataclass(frozen=True)
class CaptureFact:
    source: SourceFrame
    raw_row: tuple[int, ...]

    def check_replay(self, source: SourceFrame) -> None:
        if self.source != source:
            raise ReplayConflict(
                f'replayed source conflicts with {self.source.roll_id!r} sequence {self.source.sequence}'
            )


@dataclass(frozen=True)
class CaptureReceipt:
    roll_id: str
    sequence: int
    recording_id: str
    vibration_exceeded: bool
    origin: FrameOrigin

    def frame(self, changes: tuple[tuple[int, int], ...]) -> SourceFrame:
        return SourceFrame(
            self.roll_id, self.recording_id, self.sequence, changes,
            self.vibration_exceeded, self.origin,
        )


class EvidenceStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS capture_facts (
                roll_id TEXT NOT NULL REFERENCES runs (roll_id),
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                recording_id TEXT NOT NULL,
                vibration_exceeded INTEGER NOT NULL CHECK (vibration_exceeded IN (0, 1)),
                station TEXT NOT NULL,
                source_key TEXT NOT NULL,
                PRIMARY KEY (roll_id, sequence)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS capture_slot (
                roll_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                changes TEXT NOT NULL,
                raw_row TEXT NOT NULL,
                PRIMARY KEY (roll_id, sequence),
                FOREIGN KEY (roll_id, sequence) REFERENCES capture_facts (roll_id, sequence)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS capture_preview (
                roll_id TEXT PRIMARY KEY NOT NULL REFERENCES runs (roll_id),
                raw_row TEXT NOT NULL
            )
        ''')

    def save_prepared(self, fact: CaptureFact) -> CaptureFact:
        """Record the receipt and the recovered row in one preparation transaction.

        Each prepared sequence keeps its own resolved row, because confirmation
        lets the device reclaim the source.  The row has to survive even when a
        later frame is prepared, so it cannot live in a single overwritten slot.
        """
        source = fact.source
        existing = self.get(source.roll_id, source.sequence)
        if existing is not None:
            existing.check_replay(source)
            if fact.raw_row != existing.raw_row:
                raise ReplayConflict(f'decoded row conflicts at sequence {source.sequence}')
            return existing
        if self.read_receipt(source.roll_id, source.sequence) is not None:
            raise ReplayConflict(f'sequence {source.sequence} is no longer in the live slot')
        self.db.execute('''
            INSERT INTO capture_facts
                (roll_id, sequence, recording_id, vibration_exceeded, station, source_key)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            source.roll_id, source.sequence, source.recording_id,
            int(source.vibration_exceeded), source.origin.station, source.origin.source_key,
        ))
        changes = json.dumps([(column, format(value, 'x')) for column, value in source.changes])
        self.db.execute('''
            INSERT INTO capture_slot (roll_id, sequence, changes, raw_row) VALUES (?, ?, ?, ?)
            ON CONFLICT (roll_id, sequence) DO UPDATE SET
                changes = excluded.changes, raw_row = excluded.raw_row
        ''', (source.roll_id, source.sequence, changes, encode_row(fact.raw_row)))
        return fact

    def read_receipt(self, roll_id: str, sequence: int) -> CaptureReceipt | None:
        row = self.db.execute('''
            SELECT * FROM capture_facts WHERE roll_id = ? AND sequence = ?
        ''', (roll_id, sequence)).fetchone()
        if row is None:
            return None
        return CaptureReceipt(
            row['roll_id'], row['sequence'], row['recording_id'],
            bool(row['vibration_exceeded']), FrameOrigin(row['station'], row['source_key']),
        )

    def get(self, roll_id: str, sequence: int) -> CaptureFact | None:
        row = self.db.execute('''
            SELECT changes, raw_row FROM capture_slot WHERE roll_id = ? AND sequence = ?
        ''', (roll_id, sequence)).fetchone()
        if row is None:
            return None
        receipt = self.read_receipt(roll_id, sequence)
        changes = tuple((column, int(value, 16)) for column, value in json.loads(row['changes']))
        return CaptureFact(receipt.frame(changes), decode_row(row['raw_row']))

    def update_preview(self, fact: CaptureFact) -> None:
        # A well-formed frame fixes the baseline for the next delta even when it
        # is rejected for vibration: only its publication is suppressed.
        self.db.execute('''
            INSERT INTO capture_preview (roll_id, raw_row) VALUES (?, ?)
            ON CONFLICT (roll_id) DO UPDATE SET raw_row = excluded.raw_row
        ''', (fact.source.roll_id, encode_row(fact.raw_row)))

    def read_preview(self, roll_id: str) -> tuple[int, ...] | None:
        row = self.db.execute('''
            SELECT raw_row FROM capture_preview WHERE roll_id = ?
        ''', (roll_id,)).fetchone()
        return None if row is None else decode_row(row['raw_row'])
