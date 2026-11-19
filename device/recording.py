import json
import os
from dataclasses import dataclass
from pathlib import Path

from device.frame import SourceFrame, read_source_frame
from run.manifest import RecordingHeader, require_name, validate_header


@dataclass(frozen=True)
class DeviceRecording:
    roll_id: str
    header: RecordingHeader
    frames: tuple[SourceFrame, ...]

    def __post_init__(self) -> None:
        require_name(self.roll_id, 'roll_id')
        object.__setattr__(self, 'header', validate_header(self.header))
        object.__setattr__(self, 'frames', tuple(self.frames))

    def frame_at(self, sequence: int) -> SourceFrame | None:
        if type(sequence) is not int or sequence <= 0:
            raise ValueError('sequence must be a positive integer')
        if sequence > len(self.frames):
            return None
        return self.frames[sequence - 1]


def load_recording(path: str | os.PathLike[str]) -> DeviceRecording:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('header'), dict):
        raise ValueError('recording must contain a header object')
    if not isinstance(data.get('frames'), list):
        raise ValueError('recording must contain an ordered frames array')
    header = data['header']
    return DeviceRecording(
        data.get('roll_id'),
        RecordingHeader(header.get('recording_id'), header.get('width'), header.get('initial_row')),
        tuple(read_source_frame(frame) for frame in data['frames']),
    )
