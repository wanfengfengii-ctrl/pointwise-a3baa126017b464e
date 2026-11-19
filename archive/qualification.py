from archive.disposition import Disposition
from capture.evidence import CaptureFact

VIBRATION_REJECTION = 'vibration_exceeded'


def qualify_frame(fact: CaptureFact) -> Disposition:
    source = fact.source
    if source.vibration_exceeded:
        return Disposition(source.roll_id, source.sequence, source.origin, None, VIBRATION_REJECTION)
    return Disposition(source.roll_id, source.sequence, source.origin, fact.raw_row, None)
