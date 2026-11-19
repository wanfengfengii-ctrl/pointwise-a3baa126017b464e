import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.queue import settle
from capture.intake import pump
from device.port import DevicePort
from device.recording import DeviceRecording, load_recording
from review.export import render_handover
from review.readback import ManifestView, get_manifest
from run.lifecycle import stop_source
from run.opening import open_run
from run.workspace import initialize_workspace, open_workspace

SAMPLE = Path(__file__).with_name('samples') / 'shift.json'


@contextmanager
def block_fixture_commit(db: sqlite3.Connection, table: str, sequence: int) -> Iterator[None]:
    """Make one scoped fixture attempt fail at SQLite COMMIT via a deferred foreign key."""
    if table not in ('capture_facts', 'dispositions') or type(sequence) is not int or sequence <= 0:
        raise ValueError('invalid fixture commit target')
    db.execute('CREATE TEMP TABLE fixture_prerequisite (sequence INTEGER PRIMARY KEY)')
    db.execute('''
        CREATE TEMP TABLE fixture_deferred (
            sequence INTEGER REFERENCES fixture_prerequisite (sequence) DEFERRABLE INITIALLY DEFERRED
        )
    ''')
    db.execute(f'''
        CREATE TEMP TRIGGER fixture_block_commit AFTER INSERT ON main.{table}
        WHEN NEW.sequence = {sequence}
        BEGIN
            INSERT INTO fixture_deferred VALUES (NEW.sequence);
        END
    ''')
    try:
        yield
    finally:
        db.execute('DROP TRIGGER temp.fixture_block_commit')
        db.execute('DROP TABLE temp.fixture_deferred')
        db.execute('DROP TABLE temp.fixture_prerequisite')


def _expect_sequence(db: sqlite3.Connection, roll: str, port: DevicePort, sequence: int) -> None:
    actual = pump(db, roll, port)
    if actual != sequence:
        raise RuntimeError(f'expected confirmed frame {sequence}, got {actual!r}')


def _issue(db: sqlite3.Connection, roll: str, through: int) -> int:
    manifest_id = settle(db, roll, through=through)
    if manifest_id is None:
        raise RuntimeError(f'no new manifest through F{through}')
    return manifest_id


def run_shift(path: Path, recording: DeviceRecording) -> tuple[ManifestView, ManifestView, ManifestView]:
    roll = recording.roll_id
    port = DevicePort(recording)
    with closing(open_workspace(path)) as db:
        initialize_workspace(db)
        open_run(db, roll, recording.header)
        _expect_sequence(db, roll, port, 1)
        first_id = _issue(db, roll, 1)
        first = get_manifest(db, first_id)
        _expect_sequence(db, roll, port, 2)
        try:
            with block_fixture_commit(db, 'dispositions', 2):
                settle(db, roll, through=2)
        except sqlite3.IntegrityError as error:
            if error.sqlite_errorcode != sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY:
                raise
        else:
            raise RuntimeError('the fixture archive transaction did not fail at commit')
        _expect_sequence(db, roll, port, 3)
        if port.confirmed_position() != 3 or port.redeliver(2) is not None or port.redeliver(3) is not None:
            raise RuntimeError('the device did not confirm and reclaim the two later frames')
        stop_source(db, roll, port)
    del port
    with closing(open_workspace(path)) as db:
        middle = get_manifest(db, _issue(db, roll, 2))
        final = get_manifest(db, _issue(db, roll, 3))
        if get_manifest(db, first_id) != first or get_manifest(db, middle.manifest_id) != middle:
            raise RuntimeError('a previously issued manifest changed')
        if settle(db, roll) is not None:
            raise RuntimeError('repeating settlement issued another manifest')
        return first, middle, final


def main() -> int:
    recording = load_recording(SAMPLE)
    with TemporaryDirectory(prefix='line-scan-demo-') as directory:
        first, middle, final = run_shift(Path(directory) / 'shift.sqlite3', recording)
    actual = [
        [entry.sequence, list(entry.raw_row) if entry.raw_row is not None else None,
         entry.reason, entry.origin.station, entry.origin.source_key]
        for entry in final.entries
    ]
    expected = [
        [1, None, 'vibration_exceeded', 'LS-7', 'slot-01'],
        [2, [15, 21], None, 'LS-7', 'slot-02'],
        [3, [17, 21], None, 'LS-7', 'slot-03'],
    ]
    downstream_actual = {
        'prefixes': [first.through, middle.through, final.through],
        'middle_sequences': [entry.sequence for entry in middle.entries],
        'spreads': [entry.spread for entry in final.entries],
        'counts': [final.totals.accepted, final.totals.rejected],
    }
    downstream_expected = {
        'prefixes': [1, 2, 3], 'middle_sequences': [1, 2],
        'spreads': [None, 6, 4], 'counts': [2, 1],
    }
    f2 = next((row[1] for row in actual if row[0] == 2), None)
    if f2 != [15, 21]:
        print(f'FRAME_BASE_MISMATCH expected=[15,21] actual={json.dumps(f2)}', file=sys.stderr)
        return 1
    if actual != expected or downstream_actual != downstream_expected:
        print(f'交班核账不符 {actual!r} {downstream_actual!r}', file=sys.stderr)
        return 1
    print(render_handover(middle))
    print(render_handover(final))
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'catch_up',
        'input': {
            'initial_row': list(recording.header.initial_row),
            'frames': [
                [frame.sequence, frame.changes, frame.vibration_exceeded, frame.origin.source_key]
                for frame in recording.frames
            ],
            'archive_commit_failure_at': 2,
            'offline_settlement_bounds': [2, 3],
        },
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['capture/intake.py', 'capture/checkpoint.py', 'archive/queue.py', 'review/readback.py'],
        'oracle': '手算 [10,20] 依序替换三次，F1 只计振动剔除。F2 为 21−15，F3 为 21−17。',
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
