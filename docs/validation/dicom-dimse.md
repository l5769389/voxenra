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

实际容器测试由 `tests/test_dimse_live.py` 执行，两台各 5 项：
完整查询和批量 C-MOVE/重复导入/像素哈希、取消及重试、回传不可达、错误 AE、
真实 QML 查询导入到 2D。

原生 macOS 窗口已通过实际点击核对配置字段、连接测试反馈、患者查询、CT/MR
批量导入、2D 影像显示与精确跳转（1/16 → 8/16；位置 0.00 → 10.50 mm）。
接收文件进入专属 lab 导入目录；本次只使用合成数据。

完整回归及独立审查结果在最终交付前补入。

## 调试记录与边界

- 回环测试发现 pynetdicom 中止关联后阻塞队列仍等到 DIMSE 超时：
  在固定版本 3.0.4 的响应队列中发送唤醒哨兵，阻塞查询取消测试验证小于 1.5 秒。
- 端口释放测试使用 SO_REUSEADDR 区分 TCP TIME_WAIT 与监听器泄漏。
- 首轮 lab 测试修正了测试代码的目录合并参数与新配置 ID 用法。
  emulated dcm4chee 曾超过 5 秒才响应，lab 改用 30 秒；应用按超时报错符合预期。
- 本次实际像素验证覆盖非压缩 CT/MR。压缩、Enhanced、多帧和非影像对象仍遵循
  原有扫描器/解码器能力，不能据此宣称所有医院或设备都兼容。
- DICOM TLS、Patient Root、不同查询/存储 AE 的分离配置不在此版本范围。

复现步骤见 [DIMSE 联调](../pacs-dimse-lab.md)。
