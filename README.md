# 青汀站日观测汇交仓

青汀区域环境监测汇交中心从站点收集每日用水观测。供数员封定原始日批，调度员把明细派给区域仓，接收员按票分次入账。换班时接班仓办理剩余行，夜班核账员按原清册查欠行、实入仓、原入账号和升数。

## 运行

使用 Python 3.11 标准库。在项目根目录运行以下命令。

```text
python3 -B check_project.py
python3 -B demo.py
```

控制台提供 `check_project.py`，用于运行 `tests` 包下的完整回归。也可直接运行 `python3 -B -m unittest discover -v`。演示读取 `examples/station-day.json`，在独立临时数据目录完成封定、派件、入账、转交和补办。输出展示补办前后的分仓账、未结原行和最终合计。A 的 7 L 归东仓，B 的 11 L 归西仓，C 的 0 L 补办后增加一条东仓实入记录，联合升数为 18 L。

## 日常操作

```python
from warehouse.project import WarehouseProject
from warehouse.source.intake import prepare_draft

project = WarehouseProject('work')
project.initialize()
project.seal(prepare_draft('B1', '青汀一站', '2026-05-12', [
    {'row_id': 'A', 'origin': '北堤抄表单/01', 'liters': 7},
    {'row_id': 'B', 'origin': '南门抄表单/02', 'liters': 11},
]))
a, b = project.dispatch('morning', 'B1', ['A', 'B'], 'east')
project.post('east', a)
result = project.transfer('evening', 'B1', ['A', 'B'], 'east', 'west')
for ticket in project.pending('west', 'B1'):
    project.post('west', ticket)
report = project.audit('B1')
```

1. `prepare_draft` 保留站日、批号和输入行序，草稿可以修改。`seal` 校验整批后发布冻结清册。日为 `YYYY-MM-DD`，批内原行号唯一，出处非空。每行的升数为非负整数，零有效。封定后修改草稿不影响清册。已用批号再次封定时拒绝。
2. `dispatch(request_id, batch_id, row_ids, warehouse)` 一次发布所选行的派件，结果按原清册排序。混入未知或已派行时整次拒绝。请求号同参返回原票。`row_ids` 的输入顺序也属于原参，同号异参抛出 `AssignmentConflict`。`pending(warehouse, batch_id)` 按原序领取当前未确认且未被交接单保留的票。
3. `post(warehouse, ticket)` 返回实际仓和稳定的 `receipt_id`。仓内事务一次提交正式明细和首执。合法重投复领原号，错仓、改造票或已失资格抛出 `DeliveryRejected`。协调台账仅在收到成功回执后确认原票。`project.queries[warehouse].get_receipt(ticket_id)` 和 `list_postings(batch_id)` 可分别查原执和该批正式明细。
4. `transfer(order_id, batch_id, row_ids, source, destination)` 先持久绑定所选旧票。返回 `pending` 时原单仍可续办，保留范围内暂停领取旧票，其他范围继续办理。`completed` 的 `retained` 包含已在原仓实入的原回执，`moved` 包含已结束旧资格的未入行的新票。两个分组分别保持原清册顺序。旧仓正式入账与停票按仓内提交先后确定结局，无法确定时没有新派件。重开同参可续办或原样复领，同号异参抛出 `TransferConflict`，非法选行整单拒绝。
5. `audit(batch_id)` 对照正式清册与两仓实际已入账行。报告以清册顺序分别返回 `entries` 和 `unposted`，每笔实入包含出处、实际仓和原入账号，未结行保留原出处。各仓及联合合计使用精确整数升。未结行不计，零升实入计一行，空仓计零。未知批号抛出 `UnknownManifest`，同一原行多仓入账抛出 `DuplicatePosting`，与清册不符的正式行报告数据错误。

## 数据与回归

工作目录内有 `coordination.sqlite3`、`east.sqlite3`、`west.sqlite3`。三个库分别提交。新工作目录调用 `initialize()` 创建库表，重复初始化保留操作员已经封定的清册、原票、转交单和正式账。用同一目录构造 `WarehouseProject` 可直接继续办理。两个仓的账分别读取已提交记录，业务操作完成后可用原批号即时复核。

来源原行在 `warehouse/source` 固定，`warehouse/dispatch` 管理当前归属和领取，`warehouse/posting` 保管实入结果，`warehouse/transfer` 保存交班范围与结果，`warehouse/audit` 从正式记录重算报告。回归覆盖同值异源、非法原件、整次派发、错仓、提交失败、回执复领、余单转交、两种落账胜序、旧仓暂不可用、发布回滚、进程重开、非前缀缺行、重复实入及超大整数升。暂停场景沿 `post` 的 `after_admission` 回调排定顺序，事务回滚和失答分别沿 `before_commit` 与 `after_commit` 验证。回调异常会传给调用者，已提交仓账可按原号查询。
