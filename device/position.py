class DeviceSequenceError(ValueError):
    pass


class ConfirmationPosition:
    def __init__(self) -> None:
        self._confirmed = 0

    def read(self) -> int:
        return self._confirmed

    def advance(self, sequence: int) -> int:
        if type(sequence) is not int or sequence <= 0:
            raise DeviceSequenceError('confirmation requires a positive device sequence')
        if sequence > self._confirmed + 1:
            raise DeviceSequenceError(f'confirmation would skip sequence {self._confirmed + 1}')
        if sequence > self._confirmed:
            self._confirmed = sequence
        return self._confirmed
