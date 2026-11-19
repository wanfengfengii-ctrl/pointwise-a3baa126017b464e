from capture.checkpoint import CaptureCheckpoint
from capture.evidence import EvidenceStore
from device.port import ConfirmationUnknown, DevicePort
from run.catalog import RegisteredRun
from run.lifecycle import require_matching_port


def reconcile_confirmation(
    run: RegisteredRun, port: DevicePort, checkpoint: CaptureCheckpoint, evidence: EvidenceStore
) -> int:
    require_matching_port(run, port)
    local = checkpoint.confirmed_through(run.roll_id)
    observed = port.confirmed_position()
    if type(observed) is not int or observed not in (local, local + 1):
        raise ConfirmationUnknown(f'device position {observed!r} conflicts with local position {local}')
    if observed == local:
        return local
    if evidence.get(run.roll_id, observed) is None:
        raise ConfirmationUnknown(f'device position {observed} has no prepared frame')
    checkpoint.mark_confirmed(run.roll_id, observed)
    return observed
