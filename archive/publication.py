import sqlite3
from dataclasses import dataclass

from archive.disposition import Disposition, DispositionStore
from archive.prefix import resolved_through


class ManifestNotFound(LookupError):
    pass


class ArchiveStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManifestSnapshot:
    manifest_id: int
    roll_id: str
    through: int
    dispositions: tuple[Disposition, ...]


class ManifestStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.dispositions = DispositionStore(db)

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS manifests (
                manifest_id INTEGER PRIMARY KEY,
                roll_id TEXT NOT NULL,
                through_sequence INTEGER NOT NULL CHECK (through_sequence > 0),
                UNIQUE (roll_id, through_sequence),
                FOREIGN KEY (roll_id, through_sequence) REFERENCES dispositions (roll_id, sequence)
            )
        ''')

    def publish_prefix(self, roll_id: str, through: int) -> int | None:
        """Sign an increased continuous prefix inside the caller's archive transaction."""
        previous = self.published_through(roll_id)
        end = resolved_through(self.dispositions, roll_id, previous, through)
        if end == previous:
            return None
        cursor = self.db.execute(
            'INSERT INTO manifests (roll_id, through_sequence) VALUES (?, ?)', (roll_id, end),
        )
        return cursor.lastrowid

    def published_through(self, roll_id: str) -> int:
        row = self.db.execute('''
            SELECT COALESCE(MAX(through_sequence), 0) AS frontier FROM manifests WHERE roll_id = ?
        ''', (roll_id,)).fetchone()
        return row['frontier']

    def read_snapshot(self, manifest_id: int) -> ManifestSnapshot:
        if type(manifest_id) is not int or not 0 < manifest_id < 2**63:
            raise ManifestNotFound(f'unknown manifest {manifest_id!r}')
        row = self.db.execute(
            'SELECT roll_id, through_sequence FROM manifests WHERE manifest_id = ?', (manifest_id,),
        ).fetchone()
        if row is None:
            raise ManifestNotFound(f'unknown manifest {manifest_id}')
        roll_id, through = row['roll_id'], row['through_sequence']
        entries = self.dispositions.read_range(roll_id, 1, through)
        if len(entries) != through:
            raise ArchiveStateError(f'manifest {manifest_id} has a gap in its issued prefix')
        return ManifestSnapshot(manifest_id, roll_id, through, entries)
