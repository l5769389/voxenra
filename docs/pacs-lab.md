# 本地 PACS 联调环境

本环境使用 OrbStack 的 Docker 引擎和 Docker Compose，运行 Orthanc 与 dcm4chee 两种 PACS。
OrbStack 可以替代 Docker Desktop，仍使用 `docker` / `docker compose` 命令；本机使用
`orbstack` context。Apple Silicon 上的 dcm4chee 服务按官方镜像使用 `linux/amd64` 仿真。
参见 [OrbStack Docker 文档](https://docs.orbstack.dev/docker/)。

## 已配置的连接

| 应用内名称 | DICOMweb 根地址 | 认证 |
| --- | --- | --- |
| Lab Orthanc Open | `http://127.0.0.1:8042/dicom-web` | 无 |
| Lab Orthanc Basic | `http://127.0.0.1:8043/dicom-web` | Basic，用户名 `pacs-lab` |
| Lab Orthanc Bearer | `http://127.0.0.1:8044/dicom-web` | Bearer |
| Lab dcm4chee | `http://127.0.0.1:8080/dcm4chee-arc/aets/DCM4CHEE/rs` | 无 |

Open 和 Basic 是两个独立的 Orthanc 实例；Bearer 是 Nginx 认证网关，使用 Open 的同一份数据。
dcm4chee 使用独立的 PostgreSQL 和 LDAP 服务。共运行 6 个容器，提供 4 个应用连接入口。
所有宿主机端口仅绑定 `127.0.0.1`，数据库和 LDAP 不向宿主机发布端口。

镜像在 [compose.yaml](../docker/pacs/compose.yaml) 中固定版本：

- `orthancteam/orthanc:25.10.3`
- `nginx:1.28.0-alpine`
- `dcm4che/dcm4chee-arc-psql:5.35.0`
- `dcm4che/slapd-dcm4chee:2.6.13-35.0`
- `dcm4che/postgres-dcm4chee:17.9-35`

密码、令牌和数据库密码由准备脚本随机生成，位于 `docker/pacs/.env`，初始权限为 `0600`。
`.env` 和生成的数据、截图、报告均被 Git 忽略。应用的 `pacs.json` 仅存连接信息，
不保存密码或令牌；实验启动器将 `.env` 中的凭据注入当前应用会话。

## 启动与体验

以下命令在 main 工作目录执行：
`/Users/jun/Documents/git-repo/qt-dicom-viewer`。本地凭据、测试数据和网关挂载已迁移到此目录。

```bash
open -a OrbStack
uv run python tests/manual/pacs_lab.py prepare
docker --context orbstack compose -f docker/pacs/compose.yaml up -d
uv run python tests/manual/pacs_lab.py seed
uv run python tests/manual/pacs_lab.py install-profiles
uv run python tests/manual/pacs_lab.py launch
```

`prepare` 保留已经存在的凭据，并生成固定 UID 的合成 DICOM；`seed` 等待服务就绪后通过
STOW-RS 装入三个独立数据库。上传只存在于实验脚本，查看器本身仍只查询和下载。
`install-profiles` 更新这四个实验配置，同时保留其他已有配置和默认选择。
`launch` 打开当前 worktree 的应用并带入认证信息，关闭后会话凭据即失效。
普通 `uv run qt-dicom-viewer` 也能使用保存的地址，但 Basic/Bearer 需在详情中重新填写凭据。

在首页点击 **从 PACS 导入序列**，选择实验连接，输入患者 ID `PACSLAB-001`，点击查询。
选择检查后，勾选 `Synthetic CT volume 01`（16 张切片）与 `Synthetic MR volume 02`
（2 张切片）并导入。2D 自动打开；选中 CT 序列后可继续打开 MPR、3D 或 Tag。
设置入口在左侧栏底部，连接配置位于 **设置 → 数据源**。

合成数据共 **23 个检查、45 个序列、104 个实例**，没有真实患者信息。第一个检查包含
23 个序列，用于分页验证；第三个检查包含中文姓名 `测试^患者`。原始数据及像素 SHA-256
记录在 `docker/pacs/artifacts/source/` 和 `manifest.json`。

## 重复验证

普通回归不依赖 Docker。真实服务测试必须显式启用：

```bash
# 常规回归（真实服务测试在此跳过）
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software uv run --group dev pytest -q --junitxml=docker/pacs/artifacts/regression-tests.xml

# 四个入口的 HTTP 和真实 QML 操作
PACS_LAB_TEST=1 QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software uv run --group dev pytest tests/test_pacs_live.py -q --junitxml=docker/pacs/artifacts/live-tests.xml

# macOS 桌面上的原生 VTK / OpenGL 3D 验证
PACS_LAB_TEST=1 PACS_LAB_NATIVE=1 QT_QPA_PLATFORM=cocoa uv run --group dev pytest tests/test_pacs_live.py -q -k native --junitxml=docker/pacs/artifacts/native-tests.xml

# 短暂停止 Basic 实例，验证错误提示、恢复连接和数据持久化
uv run python tests/manual/pacs_lab.py check-restart
```

真实测试使用实验库的固定数据和数量断言；追加自己的测试数据前可先完成上述验证。
HTTP/QML 测试使用临时应用配置与导入目录，不覆盖日常应用设置。
原生 3D 测试需要实际 macOS 桌面和 OpenGL，不使用离屏测试替代。

2026-09-06 在本机 OrbStack / Docker Engine 29.4.0 上验证：

| 验证 | 结果 |
| --- | --- |
| 常规回归 | 465 通过；15 项真实服务测试在此跳过 |
| 四入口 HTTP / QML | 14 通过；原生 3D 单独执行 |
| 原生 3D | 1 通过 |
| 容器停止 / 重启 | 断连报错正确，恢复后 23 个检查完整保留 |

每个入口均验证连接测试、患者/日期/模态筛选、中文姓名、空结果、检查与序列分页、
多序列导入、像素 SHA-256 一致、取消后的文件清理、重复导入去重，以及从设置新增配置到
查询、导入、2D、MPR、Tag 的实际 QML 操作。另验证错误 Basic/Bearer 凭据被拒绝，
以及从 dcm4chee 下载的 CT 在 macOS 原生 3D 中渲染、切换设置页时隐藏、返回后恢复。
回归与原生测试各有一条既有 VTK/NumPy 弃用警告，无失败。

联调修复了两处应用问题：勾选滚动列表中的序列或更新状态时列表跳回顶部；服务器突然关闭
连接时未转换为统一的连接错误。Bearer 网关也改为动态解析 Docker DNS，避免后端容器
重建换 IP 后继续访问旧地址。

JUnit 报告、容器信息、镜像摘要及截图位于 `docker/pacs/artifacts/`。
截图包括每个入口的浏览器、2D、MPR、Tag，以及 `screenshots/dcm4chee-native-3d.png`。

### 已知范围与差异

当前应用实现 DICOMweb，不含传统 DIMSE 的 C-ECHO / C-FIND / C-MOVE / C-GET。
上述结果覆盖这组本地版本及合成的未压缩单帧 CT/MR，不代表其他服务器配置或数据格式已经验证。

本次实测中，Orthanc 对中文姓名查询 `测试*` 返回空结果，而 dcm4chee 能匹配；
两者均能正确匹配完整姓名 `测试^患者` 和按 DICOM 姓名组件书写的 `测试^*`。
应用保留用户原始查询，不替换查询条件。遇到该差异可使用完整姓名、组件通配符或患者 ID。

## 日常管理

```bash
docker --context orbstack compose -f docker/pacs/compose.yaml ps
# 暂停全部实验服务，保留数据
docker --context orbstack compose -f docker/pacs/compose.yaml stop
# 再次启动
docker --context orbstack compose -f docker/pacs/compose.yaml up -d
```

数据库及影像使用 Docker 命名卷，容器重启保留数据。当前环境已启动并完成装库，
可直接执行 `launch` 体验。已有应用进程需重新启动才能读到外部安装的配置。

服务配置参考：[Orthanc 官方 Docker 镜像](https://orthanc.uclouvain.be/book/users/docker-orthancteam.html)、
[DICOMweb 插件](https://orthanc.uclouvain.be/book/plugins/dicomweb.html)、
[dcm4chee 官方最小部署](https://github.com/dcm4che/dcm4chee-arc-light/wiki/Run-minimum-set-of-archive-services-on-a-single-host)。
## 传统 DIMSE 环境

传统 DICOM 的隔离环境、AE/回传配置与验证命令见 [DIMSE 联调](pacs-dimse-lab.md)。
本页保留原 DICOMweb 环境说明。
