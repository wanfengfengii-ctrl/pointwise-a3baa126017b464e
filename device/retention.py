from device.frame import SourceFrame


class RetentionWindow:
    def __init__(self, capacity: int, reclaim_on_ack: bool):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError('device retention capacity must be positive')
        self._capacity = capacity
        self._reclaim_on_ack = reclaim_on_ack
        self._offered: dict[int, SourceFrame] = {}

    def put(self, sequence: int, frame: SourceFrame) -> None:
        # A serial device exposes at most one unconfirmed slot.
        self._offered[sequence] = frame
        if len(self._offered) > self._capacity:
            del self._offered[next(iter(self._offered))]

    def get(self, sequence: int) -> SourceFrame | None:
        return self._offered.get(sequence)

    def retire_confirmed(self, confirmed_through: int) -> None:
        if self._reclaim_on_ack:
            for sequence in tuple(self._offered):
                if sequence <= confirmed_through:
                    del self._offered[sequence]
