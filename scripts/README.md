# 打包入口

此目录包含 macOS / Windows 构建入口、打包辅助函数、冻结程序入口及网站构建脚本。

- macOS 安装包：`bash scripts/build_macos.sh`
- Windows 安装包：`./scripts/build_windows.ps1`
- Windows 便携版：`scripts\build_windows.bat`

构建参数见 [打包说明](../docs/packaging.md)。测试与验证工具见 [测试目录说明](../tests/README.md)。

## 网站与操作手册

在项目环境中运行 `uv run python scripts/build_manual_site.py build/manual-site`。
单独运行此脚本时先安装 `pillow==12.3.0`；GitHub Pages 工作流已包含这一步。

构建会从 `docs/screenshots` 自动生成多尺寸 WebP 预览。浏览器按展示尺寸选图，
动图保留帧时长与循环设置，点击图片仍能打开原始文件。原始截图及软件内手册资源不被改写。
