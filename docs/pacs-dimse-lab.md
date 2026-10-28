# 传统 DICOM / OrbStack 联调

独立 Compose project：`qt-dicom-dimse-lab`，不复用现有 DICOMweb lab 的端口或数据卷。
只生成合成数据：23 个检查、45 个序列、104 个 CT/MR 实例；无真实患者数据。

## 启动与验证

在仓库根目录执行：

```sh
uv sync --locked --group dev
uv run python tests/manual/dimse_lab.py prepare
docker --context orbstack compose -f docker/pacs-dimse/compose.yaml up -d
uv run python tests/manual/dimse_lab.py seed
DIMSE_LAB_TEST=1 QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  uv run pytest tests/test_dimse_live.py -v
uv run python tests/manual/dimse_lab.py check-restart
uv run python tests/manual/dimse_lab.py launch
```

`seed` 通过 C-ECHO 等待服务就绪，随后用 C-STORE 写入合成数据。
默认测试不访问容器，只有 `DIMSE_LAB_TEST=1` 才运行集成测试。
不要并发运行真实集成测试或在测试时从 GUI 导入，两者使用同一个回传端口。
`launch` 使用 lab 专属配置、导入目录和应用身份，保留普通安装版的设置。

| 服务 | 本机地址 | AE |
| --- | --- | --- |
| Orthanc 25.10.3 镜像 | DICOM `127.0.0.1:14242`；HTTP `127.0.0.1:18042` | ORTHANC |
| dcm4chee 5.35.0 | DICOM `127.0.0.1:14243`；HTTP `127.0.0.1:18080` | DCM4CHEE |
| Mac 临时接收器 | 监听 `0.0.0.0:11113`；仅导入期间 | VOXENRA |

两台 PACS 的 VOXENRA 目的节点配置为 `host.docker.internal:11113`。
路径为 Mac → 已映射的容器 DICOM 端口 → PACS → `host.docker.internal` → Mac 接收器。
Orthanc 通过 `DICOM_MODALITIES` 登记；dcm4chee 的 LDAP 初始化通过
`STORESCP_AE_TITLE/HOST/PORT` 登记。LDAP 参数只在新数据卷初始化时应用。
修改目的节点后需要同步修改实际 PACS 配置，不应通过删除已有业务卷更新配置。

macOS 防火墙若提示 Python/应用接受传入连接，需按本地网络策略允许。
本 lab 无 TLS，HTTP 无认证，只用于本地合成数据。服务端发布端口均限制在本机回环地址，
LDAP/数据库未发布到宿主机；Mac 回传监听在导入结束后关闭。
dcm4chee 在 Apple Silicon 上使用 amd64 镜像，首次启动/查询可能较慢，配置超时 30 秒。

## 覆盖内容

- C-ECHO、STUDY/SERIES/IMAGE C-FIND 和 SERIES C-MOVE。
- 23 条结果跨页去重，患者/中文通配符/日期/模态筛选和空结果。
- 两个序列 18 个实例的 UID、数量和解码后像素 SHA-256 一致性。
- 重复导入合并、部分接收时取消并清理、随即重试。
- 错误 Called AE、C-ECHO 成功但回传端口错误、PACS 停止和重启。
- 实际 QML 查询 → 导入 → 2D 工作区，以及原生桌面人工操作核对。

故障注入另由 `tests/test_dimse.py` 的真实回环 DIMSE 对端覆盖：
缺失对象、错误身份、重复/冲突对象、未登记目的 AE、无关发送 AE、
失败 C-FIND、端口冲突、响应阻塞时取消与端口释放。

测试产物在 `docker/pacs-dimse/artifacts`，配置和数据目录均被 Git 忽略。
停止环境并保留数据：

```sh
docker --context orbstack compose -f docker/pacs-dimse/compose.yaml stop
```

容器互通并不代替医院内网、具体厂商 PACS、Windows 防火墙、TLS、
全部压缩和多帧格式的验收。C-GET 不在本次范围。

依据：[OrbStack 网络](https://docs.orbstack.dev/docker/network)、
[dcm4chee LDAP 镜像参数](https://github.com/dcm4che-dockerfiles/slapd-dcm4chee/blob/master/README.md)、
[pynetdicom C-MOVE](https://pydicom.github.io/pynetdicom/stable/examples/qr_move.html)。
