import json
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordingHeader:
    recording_id: str
    width: int
    initial_row: tuple[int, ...]


def require_name(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty string')


def validate_header(header: RecordingHeader) -> RecordingHeader:
    if not isinstance(header, RecordingHeader):
        raise ValueError('expected a recording header')
    require_name(header.recording_id, 'recording_id')
    if type(header.width) is not int or header.width <= 0:
        raise ValueError('width must be a positive integer')
    row = header.initial_row
    if not isinstance(row, (list, tuple)) or len(row) != header.width:
        raise ValueError('initial row does not match the recording width')
    if any(type(value) is not int for value in row):
        raise ValueError('initial row must contain integer raw codes')
    return RecordingHeader(header.recording_id, header.width, tuple(row))


def encode_row(row: tuple[int, ...]) -> str:
    return json.dumps([format(value, 'x') for value in row], separators=(',', ':'))


def decode_row(encoded: str) -> tuple[int, ...]:
    return tuple(int(value, 16) for value in json.loads(encoded))
