# 界面图标

导航和操作图标使用 SVG，由 `SvgIconProvider` 按屏幕像素密度渲染并随悬停、选中和禁用状态着色。伪彩图标由 `ColorMapIcon.qml` 绘制矢量色带。

- 工具栏通过 `AppIcon.qml` / `ToolbarAction.qml` 使用图标；新增 SVG 同时加入 `SvgIconProvider.NAMES` 与 `VoxPlane.qrc`。
- 图标默认描边色为 `#aabcc8`，可选强调色为 `#5dc4c5`；渲染时替换为界面状态色。
- 鼠标图标位于相邻的 `cursors` 目录，保留指针并复用对应工具符号。
- 已移除不再使用的 PNG 工具栏图标和旧 MPR 包装组件。历史设计提示词保留在 `docs/navigation-icon-prompts.md`、`docs/navigation-icon-monochrome-prompts.md` 和 `docs/tool-icon-design.md`，不属于运行时资源。

当前按钮视觉检查见 `docs/button-review/README.md`。
