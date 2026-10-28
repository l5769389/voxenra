# PACS 数据源与导入

点击左侧栏底部 **设置**，在独立 Tab 中打开“数据源”。支持两种连接：

- **DICOMweb**：QIDO-RS 查询检查、序列与实例，WADO-RS 下载 DICOM 实例。
- **传统 DICOM（DIMSE）**：C-ECHO 连接测试、Study Root C-FIND 查询，
  C-MOVE 请求 PACS 回传，通过仅在导入期间运行的 C-STORE 接收器接收影像。

两种协议共用查询、选择、导入和工作区浏览流程。旧配置自动按 DICOMweb 读取。
不含 C-GET，也不提供向 PACS 上传或修改数据的入口。

## 传统 DICOM 配置

设置 → 数据源 → 新增配置，将“连接协议”切换为“传统 DICOM（DIMSE）”：

| 字段 | 含义 |
| --- | --- |
| PACS 主机 / IPv4、端口 | 远端 DICOM TCP 服务，端口通常由管理员提供 |
| 远端 AE Title | PACS 的 Called AE；本版同时要求回传 C-STORE 的 Calling AE 与此一致 |
| 本机 / 接收 AE Title | 请求的 Calling AE，也是 C-MOVE Destination |
| 本机监听 IPv4、接收端口 | 在本机绑定的地址；仅在导入期间占用 |
| 网络超时 | 3–120 秒的关联、DIMSE 响应和网络等待超时；TCP 建连最多 5 秒 |

AE Title 为 1–16 个可打印 ASCII 字符，不含反斜杠，首尾空格会去掉。
主机可填 DNS 名或 IPv4；本版监听地址只接受 IPv4。

**还须在 PACS 端登记接收节点**：本机接收 AE → PACS 可访问的本机 IP → 接收端口。
这里的“本机监听地址”与 PACS 中登记的目的地址不同：`0.0.0.0` 表示本机所有 IPv4 网卡，
不能作为 PACS 的目的地址；`127.0.0.1` 只接受本机连接。
医院网络中通常监听本机局域网 IP，并按网络策略放行该端口。
如果 PACS 查询 AE 和存储发送 AE 分离，须在 PACS 端使用同一发送 AE，或使用 DICOMweb。

“测试连接”只验证 C-ECHO，**不能证明查询权限和回传链路可用**。保存后查询一条检查，
导入一个序列，才能验证 C-FIND、C-MOVE、回传和本地解码的完整链路。
远端未登记 Destination AE 会显示相应提示；监听冲突、服务端失败、超时、
缺失实例或身份不符均不会发布部分序列。

传统 DICOM 使用普通 TCP，本版未实现 DICOM TLS 或用户身份协商。
AE Title 是路由/准入标识，不是密码认证。应在可信内网或受保护的网络通道使用。
接收器只接受配置的发送 AE 和本次请求清单中的 Study/Series/SOP 身份。
未实现 Patient Root 查询、Modality Worklist、Storage Commitment 或永久接收服务。

DIMSE 分页为完整 C-FIND 结果排序后的本地分页；每页重新查询，不依赖服务器 offset。
单次检查/序列查询最多 10,000 条，实例清单最多 100,000 条，超限会提示缩小范围。
PACS 必须支持 Study Root 的 STUDY、SERIES、IMAGE 层级及 SERIES 级 C-MOVE。
完整响应前不会把失败查询显示成“无结果”。

## DICOMweb 配置与共用浏览流程

1. 设置 → 数据源 → 新增配置。填写名称和完整的 DICOMweb 根地址，
   例如 `http://127.0.0.1:8042/dicom-web`，不要在末尾附加 `/studies`。
   Orthanc 需要启用其 DICOMweb 插件；常规 Orthanc REST API 地址或 DICOM TCP 端口不适用。
2. 选择无认证、Basic 或 Bearer，可设置 3–120 秒的网络读/连接超时。
   **测试连接**会发送 `GET /studies?limit=1` 并验证 DICOM JSON，空库也视为连接成功。
   这验证查询权限；下载权限在实际导入时验证。
   列表和详情弹窗的测试结果均显示在按钮附近，无需滚动；点击立即显示「测试中…」，完成后显示成功、认证失败、超时或具体错误。各连接及未保存配置独立保留结果，修改配置或重新测试时更新。
3. 保存配置。支持多个配置、详情编辑、启停、设为默认和删除。默认配置必须启用，
   禁用或删除默认项后自动使用下一个启用项。删除配置会保留已经导入的影像。
4. 在首页点击 **从 PACS 导入序列**，或在侧栏点击 **PACS 浏览器**。
   选择连接，按患者姓名、ID、检查号、模态、日期或更多条件查询；日期默认不限制。
   日期支持手动输入、日历选择和清空，校验真实日期及起止顺序，允许单侧留空；更多条件展开后在内容底部收起。查询、检查和序列列表为滚动条预留空间。
   姓名通配符的具体匹配能力取决于服务器，常用 `Patient*`。
5. 点击检查，勾选一个或多个序列，再点击 **导入所选**。
   支持检查/序列分页、全选本页；切换检查、分页、配置会清空旧的序列勾选。
6. 下载与扫描在后台执行，显示实例进度，可取消。全部所选序列通过校验后一次加入
   左侧患者/检查列表，并打开第一个序列的 2D Tab。之后可使用已有的 MPR、3D、Tag 等入口，
   各视图仍遵循原有的数据支持条件。重复导入按 Series UID 更新列表，不重复增加条目。

本地文件与 PACS 可同时启用，至少保留一种。关闭某种数据源会隐藏对应导入入口，
已打开的影像仍可浏览。设置和 PACS 浏览器是可关闭、可再次打开的工作区 Tab。
两个数据源开关在设置中同行显示；侧栏的文件夹 / PACS 组成同色分段入口，首页 PACS 按钮使用同款 SVG。保存成功不再显示「设置已保存」，错误和连接测试反馈仍保留。

## 本机存储与认证

- 配置在 Qt `AppConfigLocation/pacs.json` 中以 JSON 原子保存，不随项目源码存放。
  密码与 Bearer 令牌**只保存在当前会话内存**，不写入配置或日志。重启后需在详情中重新填写。
  同一地址和认证账号下编辑配置可留空保留会话密码；更改地址/认证方式/账号后不会沿用旧密码。
- HTTPS 使用系统证书校验，没有关闭 TLS 校验的开关。仅允许同源 HTTP 重定向，
  避免认证信息随重定向转发至其他服务。系统代理设置仍由 Python 标准 HTTP 客户端使用。
- 影像保存在 Qt `AppLocalDataLocation/pacs-imports/import-*` 中，保证 Tab 使用的文件持续存在。
  在 macOS 上通常位于 `~/Library/Application Support/Voxenra/Voxenra/pacs-imports`；
  以实际 Qt 返回目录为准。导入后可从 series 右键菜单“在资源管理器中打开”定位文件。
  完成的下载不会自动删除；关闭应用后可手动清理不再需要的导入目录。
- 取消、数量不符、UID 不符、下载中断或扫描失败会删除本次导入目录，不把部分结果加入列表。
  DICOMweb 取消会在当前网络读取返回或达到配置的超时后生效；
  DIMSE 取消会发送 C-CANCEL 并中止关联，随后关闭临时接收器。
  应用退出同样取消并等待工作线程结束。
- WADO 请求显式协商 Explicit VR Little Endian（未压缩），支持 `multipart/related` 和
  `application/dicom` 响应。若 PACS 不支持该传输语法，会显示下载错误；不静默退回未知压缩格式。
  现有解码器、多帧和几何限制继续适用。
- DIMSE 接收器支持协商存储传输语法并保留其文件元信息，最终仍交给同一扫描器与解码器。
  协议接收成功不等于所有压缩编码或非影像 SOP Class 都可显示。

## 实现与验证

`pacs/config.py` 管理配置；`pacs/client.py` 实现 HTTP、QIDO 分页、流式 WADO 下载和 UID 校验；
`pacs/transport.py` 按协议选择客户端；`pacs/dimse_client.py` 和 `dimse_receiver.py`
实现 DIMSE 查询、回传和临时接收器；
`pacs/importer.py` 将完整下载交给现有扫描器；`ui/controller/pacs_controller.py` 管理后台任务、
选择与进度。设置分类数据与具体页面分离，未来可在 `SettingsPage.qml` 中添加其他设置分类。

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software uv run --group dev pytest tests/test_pacs.py tests/test_pacs_qml.py -q
```

测试启动仅监听 `127.0.0.1` 的临时 HTTP PACS，生成无真实患者信息的 DICOM，覆盖配置持久化、
认证、服务端分页上限、空库、错误响应、UID/数量校验、二进制 multipart 边界、完整像素下载、
取消清理，以及真实 QML 新增/测试/查询/导入和最小 1000×600 窗口布局。
另已在 OrbStack 中完成 Orthanc、dcm4chee 及 Basic/Bearer 入口的真实容器联调，覆盖
配置、查询、导入、像素一致性和 2D/MPR/Tag/原生 3D；部署步骤与结果见
[本地 PACS 联调环境](pacs-lab.md)。其他目标 PACS 仍需按实际地址、账号和影像格式验证。
传统 DICOM 的独立 OrbStack 环境与复现命令见 [DIMSE 联调](pacs-dimse-lab.md)，
实际结果见 [验证记录](validation/dicom-dimse.md)。

协议依据：[DICOM PS3.18 Search Transaction](https://dicom.nema.org/medical/dicom/current/output/chtml/part18/sect_10.6.html)、
[Retrieve Transaction](https://dicom.nema.org/medical/dicom/current/output/chtml/part18/sect_10.4.html)。
Orthanc 配置参见 [DICOMweb 插件文档](https://orthanc.uclouvain.be/book/plugins/dicomweb.html)。
