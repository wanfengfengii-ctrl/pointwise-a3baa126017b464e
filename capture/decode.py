from device.frame import FrameOrigin, SourceFrame
from run.manifest import RecordingHeader


class BadFrame(ValueError):
    pass


def validate_source_frame(
    frame: SourceFrame, roll_id: str, header: RecordingHeader, expected_sequence: int
) -> None:
    if not isinstance(frame, SourceFrame):
        raise BadFrame('expected a source frame')
    if frame.roll_id != roll_id or frame.recording_id != header.recording_id:
        raise BadFrame('source frame belongs to a different recording')
    if type(frame.sequence) is not int or frame.sequence != expected_sequence:
        raise BadFrame(f'expected device sequence {expected_sequence}, got {frame.sequence!r}')
    if type(frame.vibration_exceeded) is not bool:
        raise BadFrame('invalid vibration flag')
    origin = frame.origin
    if not isinstance(origin, FrameOrigin) or any(
        not isinstance(value, str) or not value.strip()
        for value in (origin.station, origin.source_key)
    ):
        raise BadFrame('missing or invalid named device origin')
    if not isinstance(frame.changes, tuple):
        raise BadFrame('changes must be an ordered sequence of column and value pairs')
    seen = set()
    for change in frame.changes:
        if not isinstance(change, tuple) or len(change) != 2:
            raise BadFrame('malformed column and value pair')
        column, value = change
        if type(column) is not int or not 1 <= column <= header.width:
            raise BadFrame(f'column {column!r} outside recording width {header.width}')
        if type(value) is not int:
            raise BadFrame(f'column {column} must contain an integer raw code')
        if column in seen:
            raise BadFrame(f'duplicate change for column {column}')
        seen.add(column)


def apply_delta(
    baseline: tuple[int, ...], changes: tuple[tuple[int, int], ...]
) -> tuple[int, ...]:
    """Apply an already validated delta to the complete confirmed row."""
    result = list(baseline)
    for column, value in changes:
        result[column - 1] = value
    return tuple(result)
