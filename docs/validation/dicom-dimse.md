# 传统 DICOM 验证记录（2026-10-28）

分支 `codex/dicom-dimse`，基于 `8d71ec6`，独立 worktree。
macOS / Apple Silicon；Python 3.13.14；pynetdicom 3.0.4；OrbStack Docker Engine 29.8.2。
无 C-GET、上传 UI、常驻接收器或发布包。

## 已验证

| 检查 | 结果 |
| --- | --- |
| DIMSE 配置及既有 DICOMweb/导入回归 | 76 项通过 |
| DIMSE QML 完整配置/查询/导入 | 1 项通过 |
| 既有 PACS QML / 语言 | 4 + 29 项通过 |
| PACS 可访问性 / 主题 | 15 项通过 |
| 实际 Orthanc + dcm4chee 集成 | 10 项通过，12.45 秒 |
| Orthanc 停机及重启 | 断开报错，恢复后保留全部 23 个检查 |
| 独立复核修复后的全部相关测试 | 93 项通过，包含 10 项实际容器测试 |
| 最终完整隔离回归 | 227 个文件；2,901 项通过，82 项跳过；0 失败、0 错误 |

实际容器测试由 `tests/test_dimse_live.py` 执行，两台各 5 项：
完整查询和批量 C-MOVE/重复导入/像素哈希、取消及重试、回传不可达、错误 AE、
真实 QML 查询导入到 2D。

原生 macOS 窗口已通过实际点击核对配置字段、连接测试反馈、患者查询、CT/MR
批量导入、2D 影像显示与精确跳转（1/16 → 8/16；位置 0.00 → 10.50 mm）。
接收文件进入专属 lab 导入目录；本次只使用合成数据。
第二轮原生检查从 dcm4chee 导入 CT 后，`native-state.json` 同步确认：
`activeTabType=2d`、`busy=false`、`error=false`、`seriesCount=1`、
`sliceCount=16`、非空 `imageSource`，序列 UID 与请求相同。

最终完整回归在取消修复提交 `5ddc768` 上执行，统计共 2,983 项。
完整回归不启用可选的容器测试；上述 93 项相关回归已另行启用并通过真实服务器验证。
结果保存在本地 `build/dimse/final-full/results.json` 与
`build/dimse/final-focused/results.json`，复现完整回归：

```sh
uv sync --locked --group dev --group build
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  .venv/bin/python tests/run_isolated.py --output build/dimse/final-full
```

首轮完整回归有两项环境/既有测试问题：未修改的自动分割界面出现一次 QML 警告，
单项和整文件重跑均通过；打包测试因未安装构建依赖而整模块跳过，补齐锁定的 build
依赖后 4 项通过。最终完整回归两者均通过，未因此修改业务代码。

专属 DIMSE lab 的四个容器已停止，数据卷和复现脚本保留；既有 DICOMweb lab 未改动。

## 独立代码复核

一次独立只读审查确认了配置迁移、会话凭据保留、清单校验和原子导入；
发现一项 P2：握手和释放阶段取消未覆盖。新增真实 TCP 握手阻塞、A-RELEASE 阻塞测试，
分别复现等待至超时、取消后误报成功。修复后两项均在 1.5 秒内抛出取消，
全部 13 项真实回环协议测试通过，全部相关 93 项测试通过。
没有其他重要问题或待处理的小问题。

## 调试记录与边界

- 回环测试发现 pynetdicom 中止关联后阻塞队列仍等到 DIMSE/ACSE 超时：
  固定版本 3.0.4，使用 EVT_REQUESTED 捕获握手关联，取消时唤醒响应及 ACSE 队列，
  watcher 保持到释放结束。未来依赖升级必须重跑这些生命周期测试。
- 端口释放测试使用 SO_REUSEADDR 区分 TCP TIME_WAIT 与监听器泄漏。
- 首轮 lab 测试修正了测试代码的目录合并参数与新配置 ID 用法。
  emulated dcm4chee 曾超过 5 秒才响应，lab 改用 30 秒；应用按超时报错符合预期。
- 本次实际像素验证覆盖非压缩 CT/MR。压缩、Enhanced、多帧和非影像对象仍遵循
  原有扫描器/解码器能力，不能据此宣称所有医院或设备都兼容。
- DICOM TLS、Patient Root、不同查询/存储 AE 的分离配置不在此版本范围。

复现步骤见 [DIMSE 联调](../pacs-dimse-lab.md)。

## 实施取舍

- 按用户已确认的范围直接执行并保留独立分支，不增加设计批准等待；范围若变化需另行调整。
- 配置的工厂分派与传输层一起提交，避免中间提交引用尚不存在的客户端；最终功能无差异。
- 使用固定 pynetdicom 版本的队列适配取消，以获得可预测的退出行为；升级需验证兼容性。
- 保留已约定的范围限制，未声称支持不同存储发送 AE、TLS、Windows 或所有厂商/编码。
  需要这些能力的部署必须另行开发或验收。
