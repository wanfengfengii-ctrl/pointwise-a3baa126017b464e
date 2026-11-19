import sqlite3
from dataclasses import dataclass

from archive.publication import ManifestNotFound as ManifestNotFound
from archive.publication import ManifestStore
from device.frame import FrameOrigin
from review.spread import raw_spread
from review.totals import ManifestTotals, summarize_outcomes


@dataclass(frozen=True)
class ManifestEntry:
    sequence: int
    origin: FrameOrigin
    raw_row: tuple[int, ...] | None
    reason: str | None
    spread: int | None


@dataclass(frozen=True)
class ManifestView:
    manifest_id: int
    roll_id: str
    through: int
    entries: tuple[ManifestEntry, ...]
    totals: ManifestTotals


def get_manifest(db: sqlite3.Connection, manifest_id: int) -> ManifestView:
    snapshot = ManifestStore(db).read_snapshot(manifest_id)
    entries = []
    for outcome in snapshot.dispositions:
        raw_row = outcome.raw_row
        entries.append(ManifestEntry(
            outcome.sequence, outcome.origin, raw_row, outcome.reason,
            None if raw_row is None else raw_spread(raw_row),
        ))
    return ManifestView(
        snapshot.manifest_id, snapshot.roll_id, snapshot.through, tuple(entries),
        summarize_outcomes(snapshot.dispositions),
    )
