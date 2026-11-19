import sqlite3

from capture.checkpoint import CaptureCheckpoint
from capture.decode import apply_delta, validate_source_frame
from capture.evidence import CaptureFact, EvidenceStore
from capture.reconcile import reconcile_confirmation
from device.port import ConfirmationUnknown, DevicePort
from run.catalog import RunCatalog
from run.workspace import write_transaction


def pump(db: sqlite3.Connection, roll_id: str, port: DevicePort | None) -> int | None:
    run = RunCatalog(db).get(roll_id)
    if run.source_stopped:
        return None
    if port is None:
        raise ValueError('an active roll requires its device port')
    checkpoint = CaptureCheckpoint(db)
    evidence = EvidenceStore(db)
    previous = checkpoint.confirmed_through(roll_id)
    confirmed = reconcile_confirmation(run, port, checkpoint, evidence)
    if confirmed > previous:
        return confirmed

    sequence = confirmed + 1
    prepared = evidence.get(roll_id, sequence)
    if prepared is None:
        source = port.fetch_next()
        if source is None:
            return None
        validate_source_frame(source, roll_id, run.header, sequence)
        with write_transaction(db):
            baseline = checkpoint.read_baseline(run)
            evidence.save_prepared(CaptureFact(source, apply_delta(baseline, source.changes)))
    else:
        source = port.redeliver(sequence)
        if source is None:
            raise ConfirmationUnknown(f'prepared frame {sequence} is unavailable for retry')
        validate_source_frame(source, roll_id, run.header, sequence)
        prepared.check_replay(source)

    reply = port.acknowledge(sequence)
    if type(reply) is not int or reply != sequence:
        raise ConfirmationUnknown(f'unexpected confirmation reply for sequence {sequence}: {reply!r}')
    checkpoint.mark_confirmed(roll_id, sequence)
    return sequence
