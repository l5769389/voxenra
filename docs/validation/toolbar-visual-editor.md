# 工具栏可视化编辑验收 · 2026-10-28

基于 `8adde47` 的本轮工作区改动，未制作发布包。

## 实现与复核

- 合并文字列表与单独预览，使用实际工具图标、简短名称及对应行列顺序直接编辑。
- 整块按钮可拖动；显示浮层、淡化源位置和插入标记。支持跨组插入、空组、边缘滚动、Esc／区域外取消；常用区七项上限保持原子验证。
- 选中工具后可前移、后移或转组；Alt + 左右键排序，Enter／空格进入操作栏。显式支持 macOS 的局部 Tab 路径。
- 窄窗口采用整体滚动，完整保留按钮高度与底部保存区域。沿用多窗口独立草稿、保存、取消、恢复默认行为。
- 独立代码复核发现的窄窗口宽度溢出、按钮高度裁切、键盘转组入口问题均已复现并修复；另修复键盘焦点自动滚动、连续操作焦点和原生字体宽度取整导致的省略。

## 验证结果

- `tests/test_toolbar_visual_editor.py`、`test_toolbar_customization.py`、`test_toolbar_draft_merge.py`：macOS Cocoa 原生窗口 **30 passed**。验证实际指针／键盘事件后的草稿与持久化顺序，同时检查截图。
- 三种主题，中文／英语／葡语；完整窗口 1280×720 与模拟 800×600 小屏幕，独立编辑区 390×650 与 528×502。
- 隔离全量回归 **233 文件，3,044 项：2,962 passed、82 skipped、0 failures、0 errors**。首轮沙箱阻止了九个文件内的本地监听端口或临时 DMG 操作；在本机权限下重跑全部受影响文件后通过，未修改这些产品模块。
- `git diff --check` 通过。第三方 SWIG 弃用警告仍存在，界面测试未发现 QML warning。

本地证据（均位于忽略目录）：

- `build/toolbar-visual/verified-results.json`：按文件合并的最终结果，保留各次来源。
- `build/toolbar-visual/full/`、`host-regression/`、`final-regression/`：原始日志与 JUnit。
- `build/toolbar-visual/native-final-checked.xml`：原生测试结果。
- `build/toolbar-visual/native-final-checked/test_visual_toolbar_native_lay0/`：三语言、三主题和小屏幕截图。
