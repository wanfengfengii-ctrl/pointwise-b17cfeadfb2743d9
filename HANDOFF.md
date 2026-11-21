# 同一次装夹的交班件

白班按领取的交班件各选一个平方距离，核定这些任务能否共用一套站位。站库、实收库和签发端都可在合查前关闭。`README.md` 说明现有扫描、发行、实收、单报告核定和历史报告接口。

## 签发和领取

`review.request.sign_handoff(inbox, reports, request, *, signed_by, signed_at=None) -> StoredReport` 沿用 `ReviewRequest`、签名参数和 V1 单报告核定口径，与普通报告共用报告号。报告的 `distances` 仍为升序去重的精确平方距离，单位为 mm²。原请求结构合法而没有许可摆放时也签发，距离和摆放均为空。非法请求及未知实收分别沿用 V1 的 `ValueError` 和 `LookupError`。

交班件保全每个距离与实现它的全部完整许可摆放之间的关联。报告、有序父件、首执和关联共同提交。数据库写入异常沿用 V1 传播口径，本次成果不留存，可以重试。

`reports.retrieve.get_handoff(reports, report_id) -> bytes | None` 按号领取固定的 UTF-8 JSON 交班正文。先前只签普通报告的号码及有效未知号码返回 `None`，号码格式沿用 `get_report`。领件只读已签存值，勘误及重开后同号正文保持一致。

交班正文的公开字段为 `version`（整数 `2`）、`report_id`、`batch`、`anchor_station`、`probes`、`distances`、`parents`、`receipt`、`evidence`。`probes` 为两个 `[站名, 探针名]`，`distances` 为精确有理字符串的数组。`parents` 按请求实收序排列，每对象使用 `ParentEvidence` 的字段名。`receipt` 使用 `FirstReceipt` 的字段名，`signed_at` 是 ISO 8601 UTC 时间字符串。

### evidence 编码（本实现的交付约定）

`evidence` 与 `distances` 一一对应，是三层数组：

1. 外层按 `distances` 的升序排列，每个距离一项；
2. 第二层列出实现该距离的**全部完整许可摆放**，每项是一次整组摆放；
3. 第三层按该件 `parents` 的顺序给出每个实收件的一个变换对象。

变换对象字段为 `cosine`、`sine`、`tx`、`ty`、`reflected`，前四个是精确有理字符串，`reflected` 为布尔值，作用顺序与 `review.rigid.RigidPlacement` 一致。起算站在每个整组摆放里都是零平移、`(cosine, sine) = ("1", "0")`，其 `reflected` 保留该分支实际面向。因此仅凭交班正文（配合各父件随 V1 站件携带、在签发时相同的局部坐标）即可重放全部带距离的完整摆放；旋转系数必须满足 `cosine² + sine² = 1`，否则正文判为不自洽。正文以 `json.dumps(..., sort_keys=True, separators=(',', ':'))` 编码为 UTF-8 字节，相同输入除报告号与签发时间外字节确定。

## 调用速览

```python
from review.request import ReviewRequest, sign_handoff
from review.handoff import combine_handoffs
from reports.retrieve import get_handoff

request = ReviewRequest((admission_a, admission_b), 'A', (('A', 'D'), ('B', 'F')))
stored = sign_handoff(inbox, reports, request, signed_by='Relief lead')
document = get_handoff(reports, stored.report_id)   # 固定的 UTF-8 交班正文字节
# 断库、重开后仍可按号领取同一份正文：
same_bytes = get_handoff(reopened_reports, stored.report_id)

common = combine_handoffs([(document_one, '0'), (document_two, '4')])
# common 为 None 表示无共同摆放或选定距离缺席；结构非法抛 ValueError
```

`sign_handoff` 与 `sign_review` 共用报告号序列和同一套 `ReviewRequest` 校验。`get_handoff` 对普通 V1 报告号及有效未知号返回 `None`，号码格式非法抛 `ValueError`。`combine_handoffs` 的距离接受 `int`、`Fraction` 或 `parse_rational` 可读的精确字符串，负数与浮点等非法输入抛 `ValueError`。

## 离线核定

`review.handoff.combine_handoffs(selections) -> tuple[tuple[RigidPlacement, ...], ...] | None`。`selections` 是有序列表或元组，每项为 `(交班正文字节, 所选平方距离)`。距离沿用 `station.coordinates.parse_rational` 支持的精确输入，且须非负。至少两项。同一中心的来源由交班渠道保证，报告号和接纳号在该中心内解释。全部交班件同批，以共用的确切实收件为连接关系，必须构成一个连通组。同站名出现多个实收号，或同一实收号的出处不一致，归为非法合查。跨件只按共用实收号挂接，各件仍只施加自身已核定的摆放约束。

合法合查可行时返回任意一套共同摆放。结果外层按输入项排列，内层按该件 `parents` 排列。每个 `RigidPlacement` 把对应实收件的局部毫米坐标映到共同坐标系，沿用 `review.rigid` 的作用顺序。各旋转系数和平移分量保留精确 `Fraction`。首件起算站在共同系中的平移为零，旋转系数为 `(1, 0)`，面向仍由实际分支决定。每份证据整体重定坐标时只允许平移和保向旋转，共用件每次出现的四个变换字段均须一致。

合法组中没有共同摆放，或任何所选距离不在对应件内，返回 `None`。坏格式、交班件正文不自洽、V1 输入、混批、不同实收号的同名站或未连通组抛出 `ValueError`，即使该组另有距离缺席。

## 业务样例

`examples/handoff.json` 含两组扫描及 V1 请求。`parents` 引用该组 `scans` 的键，`distances` 记录单报告预期。用 `python3 -B -m examples.handoff_preview` 可预览现有流程签出的距离、有序实收号及起算站。

- `faces` 中 `first` 与 `second` 的距离均为 `{0, 4}`。依次选 `(0, 0)` 无解，选 `(0, 4)` 有解且 B 保向。交换输入顺序和对应距离，仍须可行，结果改用新首件的起算站。`axis` 与 `second` 都选 `0` 也可行。这次 `axis` 的起算站 B 要翻面。`corrected` 使用另一条 B 实收，与 `first` 合查须报错。
- `cycle` 中 `ab`、`bc`、`ca` 各自签出零距，任选两份以零距合查均可行。三份同装时，沿 AB、BC 接入的 C 站与直接按 CA 接入的 C 站横向相差 1 mm，全组无解。
- 可沿用 `tests/test_reports.py` 在首执写入点拒写，检查没有本次成果，再移除触发器续签。追加源勘误、重开中心后按原号领件，关闭中心再做相同合查，原父件、首执和装夹资格可复核。

## 运行

保留 `python3 -B check_project.py` 对原回归的发现和失败退出。在 `.pointwise-runtime.json` 沿用现有 `version`、`kind` 和 `setup`，`verify` 运行原回归及交班核验，`demo` 演示签发、重开领件和断库后的同装裁决与可行站位。两项使用命令参数数组。
