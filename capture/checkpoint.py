import sqlite3

from capture.evidence import EvidenceStore
from run.catalog import RegisteredRun
from run.workspace import write_transaction


class CaptureStateError(RuntimeError):
    pass


class CaptureCheckpoint:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS capture_checkpoints (
                roll_id TEXT PRIMARY KEY NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                FOREIGN KEY (roll_id, sequence) REFERENCES capture_facts (roll_id, sequence)
            )
        ''')

    def confirmed_through(self, roll_id: str) -> int:
        row = self.db.execute(
            'SELECT sequence FROM capture_checkpoints WHERE roll_id = ?', (roll_id,),
        ).fetchone()
        return 0 if row is None else row['sequence']

    def mark_confirmed(self, roll_id: str, sequence: int) -> None:
        if type(sequence) is not int or sequence <= 0:
            raise CaptureStateError('invalid confirmed device position')
        with write_transaction(self.db):
            current = self.confirmed_through(roll_id)
            if sequence == current:
                return
            evidence = EvidenceStore(self.db)
            fact = evidence.get(roll_id, sequence)
            if sequence != current + 1 or fact is None:
                raise CaptureStateError(f'position {sequence} lacks the next prepared fact for {roll_id!r}')
            self.db.execute('''
                INSERT INTO capture_checkpoints (roll_id, sequence) VALUES (?, ?)
                ON CONFLICT (roll_id) DO UPDATE SET sequence = excluded.sequence
            ''', (roll_id, sequence))
            evidence.update_preview(fact)

    def read_baseline(self, run: RegisteredRun) -> tuple[int, ...]:
        preview = EvidenceStore(self.db).read_preview(run.roll_id)
        return run.header.initial_row if preview is None else preview
