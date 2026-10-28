# DIMSE 与阅片改进合并复核（2026-10-28）

## 合并范围

- 目标：当前分支 `codex/reading-controls-20261028`。
- 阅片改进先保存为 `e0f3b7b`，合入 `codex/dicom-dimse` 的 `03f5eab`。
- 两分支共同基点为 `8d71ec6`；三个语言文件自动合并，逐键核对保留两侧新增内容。
- 保留 DIMSE 分支及其独立 worktree；本轮只进行本地合并与验证。

## 复核及修正

独立只读代码审查覆盖协议选择、旧配置兼容、会话认证信息、C-FIND 查询完整性、
C-MOVE 清单校验、取消与关联释放、临时接收器清理及导入原子性，未发现需要阻止合并的代码问题。
阅片侧的日期、工具栏配置、收藏及视图区最大化沿用此前实现。

发现软件内 PACS 手册仍声称不支持 DIMSE，已修正中文、英文、葡萄牙文内容和中文源章：
补充协议选择、AE／回传地址配置、C-ECHO 的作用以及下载失败排查。网页手册由同一内容生成。
另清理连接表单中的四行尾随空格。

扩展真实 PACS 的界面验收，确认导入后检查日期、原始序列描述和患者信息与源影像一致；
点击收藏不应用窗值，视图区最大化隐藏两侧，恢复后栏宽正确。

## 验证

完整隔离回归：**232 个文件，3030 项测试；2948 项通过、82 项因环境或平台跳过，0 失败、0 错误**。
其中可选真实 PACS 测试在完整回归中跳过，已通过下述独立真实服务验证。
结果：`build/dimse-merge/full/results.json`。

- 合并前阅片相关回归：45 项通过。
- 真实 Orthanc 与 dcm4chee：10 项通过，包含查询、完整下载、UID／像素一致性、重复导入、取消重试、错误 AE 与回传失败。
- macOS Cocoa：两台服务器的原生查询／导入／阅片衔接 2 项通过；连接表单配置／测试／保存／导入 1 项通过。
- 本地手册及网页手册生成回归：23 项通过。
- 已查看原生截图并核对实际控制器和文件状态。截图位于 `build/dimse-merge/native-live/` 与 `build/dimse-merge/native-config/`，全部为合成数据。
- 本轮启动的四个专用测试容器已停止，保留原有数据卷；既有 DICOMweb 测试环境未变动。

完整日志目录：`build/dimse-merge/`。依赖由 `uv sync --locked --offline --group dev --group build` 同步。

## 验证边界

本轮运行环境是 macOS / Apple Silicon，实际服务为本机 OrbStack 中的 Orthanc 与 dcm4chee。
未进行 Windows 实机或医院厂商 PACS 联调。原有功能范围不变：Study Root C-FIND、C-MOVE、
临时 C-STORE 接收；不含 C-GET、TLS、Patient Root 或独立存储发送 AE 配置。
