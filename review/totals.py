from collections.abc import Iterable
from dataclasses import dataclass

from archive.disposition import Disposition


@dataclass(frozen=True)
class ManifestTotals:
    accepted: int
    rejected: int


def summarize_outcomes(outcomes: Iterable[Disposition]) -> ManifestTotals:
    accepted = 0
    rejected = 0
    for outcome in outcomes:
        if outcome.accepted:
            accepted += 1
        else:
            rejected += 1
    return ManifestTotals(accepted, rejected)
