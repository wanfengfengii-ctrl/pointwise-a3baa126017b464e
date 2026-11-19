def raw_spread(raw_row: tuple[int, ...]) -> int:
    """Return max minus min, in raw-code counts, for a complete nonempty row."""
    if not raw_row:
        raise ValueError('a complete raw row is required')
    return max(raw_row) - min(raw_row)
