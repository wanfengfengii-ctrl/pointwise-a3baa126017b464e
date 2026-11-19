from dataclasses import dataclass


@dataclass(frozen=True)
class FrameOrigin:
    station: str
    source_key: str


@dataclass(frozen=True)
class SourceFrame:
    roll_id: str
    recording_id: str
    sequence: int
    changes: tuple[tuple[int, int], ...]
    vibration_exceeded: bool
    origin: FrameOrigin


def read_source_frame(payload: object) -> SourceFrame:
    # Preserve malformed wire values for the capture boundary to reject atomically.
    fields = payload if isinstance(payload, dict) else {}
    changes = fields.get('changes')
    if isinstance(changes, list):
        changes = tuple(tuple(change) if isinstance(change, list) else change for change in changes)
    origin = fields.get('origin')
    if isinstance(origin, dict):
        origin = FrameOrigin(origin.get('station'), origin.get('source_key'))
    return SourceFrame(
        fields.get('roll_id'), fields.get('recording_id'), fields.get('sequence'),
        changes, fields.get('vibration_exceeded'), origin,
    )
