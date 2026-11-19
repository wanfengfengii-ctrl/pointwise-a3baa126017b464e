import sqlite3

from archive.disposition import DispositionStore
from archive.prefix import next_unresolved
from archive.publication import ArchiveStateError, ManifestStore
from archive.qualification import qualify_frame
from capture.checkpoint import CaptureCheckpoint
from capture.evidence import EvidenceStore
from run.catalog import RunCatalog
from run.workspace import write_transaction


def settle(db: sqlite3.Connection, roll_id: str, through: int | None = None) -> int | None:
    if through is not None and (type(through) is not int or through < 0):
        raise ValueError('settlement bound must be a nonnegative integer')
    with write_transaction(db):
        RunCatalog(db).get(roll_id)
        confirmed = CaptureCheckpoint(db).confirmed_through(roll_id)
        bound = confirmed if through is None else min(confirmed, through)
        manifests = ManifestStore(db)
        previous = manifests.published_through(roll_id)
        dispositions = DispositionStore(db)
        first = next_unresolved(dispositions, roll_id, previous, bound)
        if first is not None:
            evidence = EvidenceStore(db)
            for sequence in range(first, bound + 1):
                if dispositions.get(roll_id, sequence) is not None:
                    continue
                # The device reclaims a confirmed source, and a later frame
                # replaces the live baseline.  The outcome therefore has to be
                # built from the row recovered and stored at that sequence, not
                # from whatever row the roll has advanced to by settlement time.
                fact = evidence.get(roll_id, sequence)
                if fact is None:
                    raise ArchiveStateError(f'confirmed frame {sequence} lacks evidence for {roll_id!r}')
                dispositions.record(qualify_frame(fact))
        return manifests.publish_prefix(roll_id, bound)
