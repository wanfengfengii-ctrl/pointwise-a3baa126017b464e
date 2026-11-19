from collections.abc import Callable, Iterable, Mapping

from device.frame import SourceFrame
from device.position import ConfirmationPosition, DeviceSequenceError
from device.recording import DeviceRecording
from device.retention import RetentionWindow
from run.manifest import RecordingHeader


class ConfirmationUnknown(RuntimeError):
    pass


class DevicePort:
    def __init__(
        self,
        recording: DeviceRecording,
        *,
        capacity: int = 1,
        reclaim_on_ack: bool = True,
        lose_ack: Iterable[int] = (),
        pause_ack: Iterable[int] = (),
        replays: Mapping[int, SourceFrame] | None = None,
        on_ack_request: Callable[[int], None] | None = None,
    ):
        self._recording = recording
        self._position = ConfirmationPosition()
        self._retention = RetentionWindow(capacity, reclaim_on_ack)
        self._lose_ack = set(lose_ack)
        self._pause_ack = set(pause_ack)
        self._replays = dict(replays or {})
        self._on_ack_request = on_ack_request
        self._stopped = False

    @property
    def roll_id(self) -> str:
        return self._recording.roll_id

    @property
    def header(self) -> RecordingHeader:
        return self._recording.header

    def fetch_next(self) -> SourceFrame | None:
        if self._stopped:
            return None
        sequence = self._position.read() + 1
        offered = self._retention.get(sequence)
        if offered is None:
            offered = self._recording.frame_at(sequence)
            if offered is not None:
                self._retention.put(sequence, offered)
        return offered

    def redeliver(self, sequence: int) -> SourceFrame | None:
        if self._stopped:
            return None
        offered = self._retention.get(sequence)
        if offered is None:
            return None
        return self._replays.pop(sequence, offered)

    def acknowledge(self, sequence: int) -> int:
        if type(sequence) is not int or sequence <= 0:
            raise DeviceSequenceError('confirmation requires a positive device sequence')
        current = self._position.read()
        if sequence <= current:
            return current
        if self._stopped or sequence != current + 1 or self._retention.get(sequence) is None:
            raise DeviceSequenceError(f'device sequence {sequence} is not the outstanding slot')
        if self._on_ack_request is not None:
            self._on_ack_request(sequence)
        if sequence in self._pause_ack:
            self._pause_ack.remove(sequence)
            raise ConfirmationUnknown(f'confirmation interrupted before device advancement at {sequence}')
        confirmed = self._position.advance(sequence)
        self._retention.retire_confirmed(confirmed)
        if sequence in self._lose_ack:
            self._lose_ack.remove(sequence)
            raise ConfirmationUnknown(f'confirmation reply lost at {sequence}')
        return confirmed

    def confirmed_position(self) -> int:
        return self._position.read()

    def stop(self) -> None:
        self._stopped = True
