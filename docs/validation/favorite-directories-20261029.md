# 收藏目录验证（2026-10-29，内嵌列表版）

本记录对应用户最后要求：收藏目录直接显示在影像选择对话框上方，不使用下拉菜单。

## 界面检查

macOS Cocoa、Qt Quick software，通过真实 Qt 鼠标和键盘事件检查界面及实际状态：

- 收藏当前目录，保留收藏数据；修改地址但尚未确认时，不会错误收藏旧目录。
- 对话框顶部直接列出收藏目录，点击进入，再确认导入；以三张合成 CT 验证导入后能打开 2D 视口并达到 ready，截图确实显示影像。
- 失效目录不删除收藏，不覆盖原有有效路径；异步导航显示错误。
- 12 项收藏、880/620 像素窗口下最多显示两行，剩余收藏可滚动访问，无横向滚动。
- 管理弹窗修改名称后，收藏列表即时更新；重建控制器与对话框后名称和列表保持。
- 原侧栏下拉组件已移除；普通首页、侧栏、折叠侧栏及快捷键导入通过。
- 查看暗色、浅色和窄窗口截图，均正常。

新增 UI 测试为 `tests/test_favorite_directories_ui.py`。管理中的系统目录选择器由固定返回路径替代；收藏按钮、目录点击、管理编辑和实际导入执行真实 UI 事件。

截图位于本地忽略目录 `build/favorite-directories/inline-ui/`：`inline-favorites-dark.png`、`inline-favorites-light-620.png`、`inline-favorites-light-880.png`、`inline-favorite-imported.png`。

## 回归

- 原生 UI 与导入、侧栏样式及键盘：44 passed，见 `build/favorite-directories/inline-ui.log`。
- 最后补充的滚动到底部并点击收藏操作：见 `build/favorite-directories/inline-final.log`。
- 收藏存储、导入弹窗、路径记忆与手册：见 `build/favorite-directories/inline-regression.log`。
- `git diff --check` 通过。

未测试 Windows 原生界面。本轮不打包发布。

## 交互优化复核

- 收藏项按窗口宽度分配列宽，保留两行上限；“管理收藏”改为轻量文字入口。
- 同名收藏补充上级目录名称，悬停可查看完整路径。
- 收藏列表 Enter/Space 只切换目录，不触发对话框默认导入；点击当前目录保留文件选择，同一目录正在加载时重复点击不重启导航。
- 收藏刷新保留键盘焦点项与滚动位置；名称保存只在非空且确实变化时启用。
- 失效收藏错误显示对应路径，采用纯文本换行，继续保留已有有效目录。
- 原生 Cocoa：收藏 UI、原导入 UI、收藏存储回归合计 38 passed。日志 `build/favorite-directories/optimized-ui.log`，截图 `build/favorite-directories/optimized-ui/`；已查看暗色及浅色窄窗口截图。

## 拖动排序

收藏管理移除上移/下移按钮，按住条目拖动到插入位置，松手一次性保存；支持滚动到列表边缘继续拖动，Esc 取消。取消后表格选中行与下方详情保持一致。四角信息移除上移/下移按钮，使用带拖动把手的条目调整当前角落内部顺序，显示插入线；松手保存，Esc、页面隐藏或失去焦点取消。四角保留 Alt+上下键作为键盘调整方式。

原生 UI 真实鼠标按下/移动/松开验证：收藏双向拖动、取消后顺序和选中项不变、重载持久化；四角拖动、取消、即时预览、重载配置后顺序保留。截图 `build/favorite-directories/drag-ui/manager-dark.png` 与 `corner-drag-saved.png` 已检查。相关设置、收藏回归 72 passed；修正取消后的选中状态并稳定测试窗口激活及布局等待后，最终针对性原生 UI 6 passed，日志 `build/favorite-directories/drag-final.log`。

## 激活收藏项快捷取消

激活项右上角增加无边框“×”，悬停显示“取消收藏”；目录名为按钮预留空间。取消收藏仅更新收藏配置，不导航、不改变文件选择、不删除文件。最后一项移除后隐藏收藏区域，当前目录可重新收藏。保存失败时保留收藏并显示原有错误提示。

macOS Cocoa 原生点击验证了移除、重载持久化、文件选择保持、保存失败和最后一项移除。暗色及浅色截图已检查，位于 `build/favorite-directories/close-ui/`。收藏及导入回归：56 passed、4 skipped（未启用 VOXENRA_NATIVE_QA 的额外桌面验收），日志 `build/favorite-directories/close-ui.log`；`git diff --check` 通过。
