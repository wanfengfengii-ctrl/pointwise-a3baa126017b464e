import sqlite3

from device.port import DevicePort
from run.catalog import RegisteredRun, RunCatalog, RunConflict


def require_matching_port(run: RegisteredRun, port: DevicePort) -> None:
    if port.roll_id != run.roll_id or port.header != run.header:
        raise RunConflict(f'device recording does not match roll {run.roll_id!r}')


def stop_source(db: sqlite3.Connection, roll_id: str, port: DevicePort) -> RegisteredRun:
    catalog = RunCatalog(db)
    run = catalog.get(roll_id)
    require_matching_port(run, port)
    port.stop()
    return catalog.mark_source_stopped(roll_id)


def is_source_stopped(db: sqlite3.Connection, roll_id: str) -> bool:
    return RunCatalog(db).get(roll_id).source_stopped
