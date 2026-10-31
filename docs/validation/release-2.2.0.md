# Voxenra 2.2.0 发布验收

正式标签 `v2.2.0` 指向 `9ae3dd3402beb86a6c31ecab73d0e8e5a859946f`。中英文 README、网站和操作手册更新了 CPR 操作说明及公开心脏 CTA 示例。[发布页](https://github.com/l5769389/voxenra/releases/tag/v2.2.0) · [截图记录](release-2.2.0-media.md)

| 平台 | 最终提交上的结果 |
| --- | --- |
| macOS arm64 | 256 个文件，共 3,374 项，3,290 通过，84 条件跳过。DMG 完整性、应用架构、版本、ad-hoc 签名及冻结应用像素解码检查通过。 |
| Windows x64 | 256 个文件，共 3,374 项，3,278 通过，96 条件跳过。原生导入、键盘焦点、重复打开更新窗口、三轮异步切换、安装版及便携版解码、覆盖安装和启动检查通过。[构建与测试](https://github.com/l5769389/voxenra/actions/runs/41194612604) |

从真实 2.1.5 macOS 应用使用生产升级流程安装最终 DMG，核对了启动确认、版本、设置与既有工作区文件。升级后的应用打开了公开 CTA 工作区，下一采样点将横截面位置从 123.754987 mm 移至 124.253999 mm。

此前候选在 Windows 暴露了独立窗口关闭时的空视口绑定、CPR 视口可见前的焦点交接，以及主题对象销毁后的信号连接问题。更新窗口的回归场景补充了 Qt 延迟销毁事件处理。最终候选的相关测试及完整回归均通过。

macOS 采用 ad-hoc 签名，未经 Apple 公证。Windows 包无 Authenticode 签名。Windows 安装和更新检查在 Actions 上运行，完整的旧客户端点击更新及人工阅片未在 Windows 实机执行。

六个附件先上传草稿，核对 GitHub 摘要、校验文件、更新器包选择及提交后公开。[Windows 产物归档](https://github.com/l5769389/voxenra/actions/runs/41199018339)复用了同一提交的已验证产物。发布后核实 Latest、标签提交以及三个实际下载地址，三个包均返回 HTTP 206，响应总大小与附件一致。

| 安装包 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `Voxenra-2.2.0-macos-arm64.dmg` | 120376892 | `8cd8eb4fa08b75b366b0f859e37b0ff427f5471191443b95d3b8c5c53b99fccb` |
| `Voxenra-2.2.0-windows-x64-setup.exe` | 126091068 | `18163c0df44446b243390c4c60dc4476645baef38579b8d75982926f5308f37e` |
| `Voxenra-2.2.0-windows-x64-portable.exe` | 192809828 | `1d2a0845b7f999f48347774ea86fc139301c3f90c049b03986e5e96939644462` |
