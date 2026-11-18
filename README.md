# 线扫描档案与离线复核

带材厂 A 线的采集程序把带修订号的原始整数系数交给归档员。质控员按疑似划痕坐标领取自足窗口包，在隔离终端复核原始计数。接班人用核账明细中的包 ID、修订和窗口找回同一份证据。

使用 Python 3.11 标准库和 SQLite。在项目根目录运行。

```sh
python3 -B -m unittest discover -s tests -v
python3 -B station.py demo
```

演示在临时目录登记两个固定修订，取出原修订的一列，关闭档案后重建并导出阈值 28 的复核明细。命令行也可处理单独的业务步骤。下例中的 `<包ID>` 取自发布命令的输出。

```sh
python3 -B station.py register line.sqlite samples/line.json
python3 -B station.py get-block line.sqlite A017 r1 1 HL 0 1
python3 -B station.py publish line.sqlite packages A017 r1 0 3 1 4
python3 -B station.py read packages '<包ID>'
python3 -B station.py inspect packages '<包ID>' 28
```

## 数据口径

窗口和原块的矩形都按 `top, left, bottom, right` 表示，使用零基半开坐标。窗口位于原数组中，原块位于所属子带中。块行、块列是原块的标识，块边界可独立决定。登记样例的 `layout` 从细到粗逐项给出每层原行列数。子带名称第一位表示横轴低频或高频，第二位表示纵轴。只有最粗层显式登记低低子带，各层空子带不登记块。整个有效子带必须由原块无重叠地覆盖。块载荷按行优先保存整数。

每层先逆纵轴，再逆横轴。对于长度大于一的轴，偶位 `E[i] = L[i] - (H[i-1] + H[i] + 2) // 4`，奇位 `O[i] = H[i] + (E[i] + E[i+1]) // 2`。除法向下取整，邻位按整轴对应的高频或低频域夹取。单像元轴保留低频值。较粗层恢复的数组供下一细层作为低低输入。原块目录按实际结构依赖生成，零系数同样参与依赖判定。

## Python 接口

- `catalog.archive.open_archive(path)` 打开并初始化档案。返回的连接由调用者关闭。重复初始化保留固定修订、载荷和用户追加的表及数据。
- `catalog.registration.register(connection, revision, blocks)` 接收 `Revision` 和一组 `BlockInput`，返回 `RevisionKey`。布局、覆盖、身份冲突和写入失败由 `RegistrationError` 表示。修订与原块同时可查。
- `coefficients.storage.get_block(connection, key)` 按 `BlockKey` 返回原块的 `ref`、原编码 `payload` 和行优先整数 `values`。缺失或校验错误触发 `BlockDataError`。`catalog.revisions.find_revision` 找不到固定修订时触发 `RevisionNotFound`。
- `bundle.publish.publish_window(connection, directory, key, window)` 返回包 ID。无效窗口触发 `WindowError`，取件失败触发 `BlockDataError`，提交失败触发 `PackageStoreError`。包保存为 `<包ID>.json`。目录须支持同目录硬链接，已有同 ID 的完整同内容包可重复领取。
- `replay.window.read_window(directory, package_id)` 返回原点和整数行矩阵。`replay.open.open_package` 可先打开同一包，再交给 `replay.window.replay_window`。绑定错误、缺少必需原块或载荷错误会拒绝读取。
- `quality.inspection.inspect_window(directory, package_id, threshold)` 返回绑定包、修订、窗口和整数阈值的明细。点位使用原行列坐标，等于阈值也入选。`quality.export.export_receipt(receipt)` 返回 UTF-8 JSON 字节，保留行优先点位顺序和零命中的来源信息。

复制一个已发布包到离线目录即可复核。包 ID 绑定规范化清单，原块摘要绑定载荷字节。归档和包目录均为本地业务数据。发布只会在全部取件和核验完成后提交文件，提交失败时先前已领取的包仍可打开。
