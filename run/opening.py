import sqlite3

from run.catalog import RegisteredRun, RunCatalog
from run.manifest import RecordingHeader, require_name, validate_header


def open_run(db: sqlite3.Connection, roll_id: str, header: RecordingHeader) -> RegisteredRun:
    require_name(roll_id, 'roll_id')
    return RunCatalog(db).register(roll_id, validate_header(header))
