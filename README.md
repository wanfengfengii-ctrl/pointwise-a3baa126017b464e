# 带材线扫采集交班

早班采集员从线扫控制器接管带材的逐行原码。控制器确认后可立即覆写源帧。质检员独立裁决振动超限，并按连续设备序号签发清单。夜班复核员在控制器停机后仍可按原清单号领取逐帧结果。

## 运行

使用 Python 3.11 标准库和 SQLite。在项目根目录执行。

```text
python3 -B check_project.py
python3 -B demo.py
```

平台物化时提供 `check_project.py`。也可用 `python3 -B -m unittest discover -s tests -t . -v` 直接发现完整回归。演示在测试临时目录中建立工作区，读取 `samples/shift.json`，实际采集、入档、停源并重开。演示最后输出交班清单及结构化核账结果，核账不符时非零退出。

## 工作区与公开入口

```python
from contextlib import closing

from archive.queue import settle
from capture.intake import pump
from device.port import DevicePort
from device.recording import load_recording
from review.export import render_handover
from review.readback import get_manifest
from run.lifecycle import stop_source
from run.opening import open_run
from run.workspace import initialize_workspace, open_workspace

recording = load_recording('samples/shift.json')
port = DevicePort(recording)
with closing(open_workspace('shift.sqlite3')) as db:
    initialize_workspace(db)
    run = open_run(db, recording.roll_id, recording.header)
    while pump(db, run.roll_id, port) is not None:
        pass
    stop_source(db, run.roll_id, port)
    manifest_id = settle(db, run.roll_id)
    if manifest_id is not None:
        print(render_handover(get_manifest(db, manifest_id)))
```

- `open_workspace(path)` 返回由调用者关闭的连接。`initialize_workspace(db)` 建立缺失的结构，可以重复运行。初始化不会导入或重置录制。同一端口由一个采集调用者串行操作。业务写入口管理自身事务，调用时使用无未提交事务的工作区连接。
- `open_run(db, roll_id, header)` 返回已登记卷。`RecordingHeader` 的字段为录制身份 `recording_id`、正行宽 `width` 与同宽整数 `initial_row`。同号同参返回原卷。同号冲突抛出 `RunConflict`，非法值抛出 `ValueError`。停源状态随卷保存。
- `pump(db, roll_id, port)` 返回本次新增或查证确认的设备序号。已停源或录制耗尽返回 `None`。坏帧抛出 `BadFrame`，重投内容或出处冲突抛出 `ReplayConflict`。确认回包丢失、无法查证或位置矛盾时抛出 `ConfirmationUnknown`，保留已提交的待确认原件。调用者可用原端口再次调用 `pump`。`EvidenceStore.get` 可查看指定序号的准备证据，只有 `CaptureCheckpoint.confirmed_through` 覆盖的序号可以入档。
- `DevicePort` 用确定性录制模拟先曝光、后确认的设备。`lose_ack` 指定实际确认后丢弃回包的序号，`pause_ack` 指定确认前中断一次的序号，`replays` 可为留存内的指定源件配置一次具名重投。确认后默认立即回收。`stop_source(db, roll_id, port)` 核对卷和录制身份后停止新源件交付并记录停源。同参重开后 `settle` 和 `get_manifest` 可在无端口时使用。
- `settle(db, roll_id, through=None)` 从已签前沿后的首个缺口开始，最多处理到 `through` 指定的闭区间上界，省略上界则处理当前已确认范围。`through=0` 表示空范围。返回本次新签清单号，无新增前缀则返回 `None`。SQLite 入档提交失败抛出原异常，回滚本次新增终局和清单，确认位置与已接管证据仍可用。
- `get_manifest(db, manifest_id)` 返回固定号、卷号、截止序号、有序条目与合格剔除计数。未知号抛出 `ManifestNotFound`。合格条目有完整 `raw_row` 和整数 `spread`。剔除条目有 `reason`，原码和极差均为 `None`。所有条目都保留 `origin`。后续签发不改变旧号的结果。

## 录制与核账

录制 JSON 包含 `roll_id`、`header` 与有序 `frames`。每帧含卷号、录制身份、一基 `sequence`、`changes`、布尔值 `vibration_exceeded` 和 `origin`。`changes` 是 `[列号, 新原码]` 对的数组，列号从 1 起且帧内不得重复。空数组保留上一已确认行，但仍产生独立设备序号和终局。原码只接受整数，布尔值不作为整数接收。`origin` 由 `station` 和 `source_key` 组成。装载录制时先校验录制头，坏帧保留到采集入口处理，缺失字段、坏差量或序号不符均整帧拒绝。

样例从 `[10,20]` 开始。F1 改第一列为 15 并因振动剔除，F2 只改第二列为 21，F3 只改第一列为 17。演示在 F2 入档提交暂败后仍确认 F3，停源重开后分别签至 F2、F3。F2 应领得 `[15,21]` 及极差 6，F3 应领得 `[17,21]` 及极差 4。两条极差都以原码计数为单位，按全行最大值减最小值计算。到 F2 的固定清单只有一条合格和一条剔除，签至 F3 后旧号内容仍相同。F1 只有剔除理由和原出处。
