from decimal import Decimal

from review.readback import ManifestView


def render_handover(view: ManifestView) -> str:
    lines = [f'清单 {view.manifest_id}  卷 {view.roll_id}  截止 F{view.through}']
    for entry in view.entries:
        origin = f'{entry.origin.station}/{entry.origin.source_key}'
        if entry.raw_row is None:
            lines.append(f'F{entry.sequence}  {origin}  剔除 {entry.reason}')
        else:
            values = ', '.join(str(Decimal(value)) for value in entry.raw_row)
            lines.append(f'F{entry.sequence}  {origin}  [{values}]  极差 {Decimal(entry.spread)} 原码计数')
    lines.append(f'合格 {view.totals.accepted}  剔除 {view.totals.rejected}')
    return '\n'.join(lines)
