# 分幅复测计量台账

白班站员从分幅扫描导出中登记标记、探针和扫描面许可。夜班中心根据指定实收件核定整组是否能同时摆放，接班质控员按报告安排复测并核对原据。站端和中心使用各自的 SQLite 文件，交接材料为 V1 站件字节。

## 运行

在项目根目录使用 Python 3.11 和标准库。控制台物化项目时提供完整回归入口。演示和测试均在临时目录创建数据库。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`examples/day_shift.json` 是一组扫描与 C 站勘误。原版中 P 和 Q 分别要求相邻站同侧，R 要求 A、C 反侧，三个条件无法同时满足。勘误后距离为 `1` mm²。演示关闭站库后签发两份报告，重开后按号复领。`examples/offline_packets.json` 另含可独立导入的合法 V1 对象，每个对象可用 `json.dumps(obj).encode('utf-8')` 转为站件。

## 源修订和发行

用 `sqlite3.connect` 打开站库，在空闲连接上创建 `station.source_store.SourceStore(connection)` 和 `issue.catalog.IssueCatalog(connection)`，分别调用 `initialize()`。各入口自行提交业务写入。调用方负责关闭连接，重复初始化保留已有记录。

- `station.ingest.ingest_scan(source_store, scan)` 返回新修订号。扫描字典包含 `batch`、`station`、`source`、`face`、`markers`、`probes`。扫描面取 `fixed` 或 `reversible`。两份点目录分别以 `[名称, [x, y]]` 为条目，容许空目录和同名同位置的等价读值。同目录内同名异位会拒绝整笔。读值为整数、`Fraction` 或 `Fraction` 可精确读取的字符串，例如 `"-2/3"` 或 `"0.125"`。浮点、布尔值、零分母和非法点均拒绝。名称及来源为无首尾空白的非空字符串。
- `SourceStore.read_current_revision(batch, station)` 返回当前修订号，尚无记录时返回 `None`。有效勘误追加修订并原子切换当前指针。原始扫描及来源留在站库。
- `issue.packet.issue_packet(source_store, catalog, batch=..., station=..., revision=...)` 返回 `IssuedPacket`，包括 `issue_id`、确切身份、站端来源和 `packet` 字节。指定修订与站或批次不符时抛出 `ValueError`，无新增发行。
- `issue.catalog.get_packet(catalog, issue_id)` 读取旧站件的确切字节和出处。有效号码未找到时返回 `None`。

V1 是 UTF-8 JSON。外层包含 `version`、`identity` 和 `body`。正文包含独立的 `identity`、布尔 `allow_flip` 以及 `markers`、`probes` 两个点对象。两份身份都包含 `batch`、`station`、`revision`、`issue_id`，号码为正的 SQLite 整数。点对象以点名为键，以两个有理读值为值，发行器使用精确字符串。全部点共享毫米制相对坐标和定向，发行器对标记与探针施加同一平移，扫描面的上下关系得以保留。中心允许来件采用任意共同的局部原点。发行号码由站库分配，在站别、批次及修订上下文中与字节一起核对。

## 中心实收、核定和复领

在中心的独立 SQLite 连接上创建 `intake.inbox.IntakeInbox(connection)` 和 `reports.store.ReportStore(connection)`，分别调用 `initialize()`。站库可以在复测前关闭。

- `intake.receipts.receive_packet(inbox, packet, received_from=...)` 解码字节并比对外层与正文身份。合法来件保存原字节、接纳号、SHA-256 和首次实收来源。相同身份及字节再次实收会返回原接纳号和原来源，同一身份下的不同字节会拒绝。格式非法、重复 JSON 键或身份不符时抛出 `ValueError`，实收目录无新增。
- `review.request.ReviewRequest((a_id, b_id), 'A', (('A', 'D'), ('B', 'F')))` 指定有序接纳号、起算站和两个按所属站定位的目标探针。探针引用可重复。每次选同批两至三站，站别唯一。若两站有共名标记，至少有一对共名标记在双方各自位置均不同，且由这样的接缝形成连通图。非法请求抛出 `ValueError`，未知接纳号抛出 `LookupError`。
- `review.request.sign_review(inbox, reports, request, signed_by=..., signed_at=...)` 返回定稿。`signed_at` 可省略以使用当前 UTC 时间，也可传入带时区的 `datetime`。起算站固定平移、旋转基准，保留许可的面向。每站最终摆放须满足自身扫描面许可及其参与的全部接缝。结构合法但点间长度、其余共有点或闭合接缝无法相容时，正常签空集。`distances` 是数值升序去重的 `Fraction` 元组，单位 `mm²`。两探针合法重合时含 `Fraction(0)`。报告、按请求排序的父件和首执同时提交，SQLite 写入错误会回滚并传播给调用方。
- `reports.retrieve.get_report(reports, report_id)` 按号读取已存距离、原探针请求、有序父件及首次签发人和时间。父件包含接纳号、站别、批次、修订、发行号、首次实收来源及字节摘要。有效号码未找到时返回 `None`。复领不用站库或重新核定。再次调用签发入口会产生独立定稿。

## 正常回归

完整套件位于 `tests`。发行测试覆盖勘误后仍可按旧号发行、定向关系和输入拒绝。实收测试覆盖独立站件、身份不符和重复实收。复测测试覆盖闭环、只有两条接缝的连通链、扫描面、零距、有理旋转和混批拒绝。报告测试用真实 SQLite 触发器在首执写入点检验回滚，再重试和重开复领，核对父件次序、定稿、首执和当前修订。
