from archive.disposition import DispositionStore


def resolved_through(store: DispositionStore, roll_id: str, after: int, through: int) -> int:
    if through <= after:
        return after
    expected = after + 1
    for sequence in store.sequences(roll_id, expected, through):
        if sequence != expected:
            break
        expected += 1
    return expected - 1


def next_unresolved(store: DispositionStore, roll_id: str, after: int, through: int) -> int | None:
    first = resolved_through(store, roll_id, after, through) + 1
    return first if first <= through else None
