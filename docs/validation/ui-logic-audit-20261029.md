# UI 与交互逻辑复核（2026-10-29）

范围：本轮未提交界面变更，重点为收藏目录、收藏管理拖动、四角直接编辑；回归还覆盖设置、工作区交互、页签、手册和本地导入。此次仅审核，未修改产品代码。原生交互在 macOS Cocoa 下运行；未覆盖 Windows 原生窗口或整套软件的所有分析功能。

## 确认的问题

### P2：导入框销毁后仍执行收藏关闭按钮的定位回调

位置：`src/qt_dicom_viewer/ui/dialogs/local_import_dialog.py:339`、`:389`，异常落点 `:306`。

Resize/Show 使用无 QObject 上下文的 `QTimer.singleShot(0, self._position_favorite_remove)`。关闭并销毁导入框后，排队的回调仍访问已删除的 QListWidget。扩展回归真实出现 `RuntimeError: Internal C++ object ... already deleted`；随后用“显示—调整大小—关闭销毁—处理事件”的独立探针再次复现。不能据此推断必然导致整个进程崩溃。

建议：使用由对话框拥有的单次 QTimer 合并定位请求，关闭时停止；将回调生命周期绑定至 QObject，必要时加有效性检查。

### P2：收藏排序窗口失焦后仍继续拖动并保存

位置：`src/qt_dicom_viewer/ui/dialogs/reorder_table.py:112`。

取消逻辑在 `changeEvent` 中匹配 `WindowDeactivate`，实际窗口失焦没有进入该处理。原生鼠标开始拖动后激活另一个窗口，原窗口 `isActiveWindow=False`，表格仍 `_dragging=True`，自动滚动计时器仍启动；在原位置释放后收藏顺序发生了变化。

建议：在正确的事件入口监听所属顶层窗口失焦，并处理鼠标抓取丢失；取消手势后松开鼠标不得提交排序。

### P2：添加、替换收藏时目录检查阻塞 GUI 线程

位置：`src/qt_dicom_viewer/ui/controller/favorite_directories_controller.py:66`。

`resolve(strict=True)`、`is_dir`、`os.access`、`os.scandir` 由按钮直接同步调用。对慢盘或网络挂载，检查延迟会阻塞整个事件循环。探针仅模拟 scandir 延迟 300 ms，按钮调用耗时约 308 ms，期间 10 ms Qt 心跳一次也未执行。这里只证明慢 I/O 的阻塞机制，未实测网络故障的实际等待上限。

建议：目录验证放到后台，提交前重新检查去重/数量及请求是否仍有效；等待期间显示验证状态并避免重复提交。

### P2：四角示例没有反映外观设置

位置：`src/qt_dicom_viewer/qml/sections/settings/CornerLayoutEditor.qml:119`。

示例文字固定为 11 px、固定颜色，行高固定；与下方字号、行距、颜色设置无绑定。将字号改为 20、行距改为 1.8、自定义颜色改为绿色后，截取四角编辑区的图像与修改前逐像素相同。真实影像叠加层仍使用这些配置，因此这是设置预览与实际效果不一致，不是保存失效。

建议：保留可操作的编辑控件尺寸，让示例值使用实际叠加层的外观配置；若需要固定编辑行高，则补充能真实反映字号、行距和颜色的预览。

## 验证记录

- 扩展回归：178 passed、1 failed、3 skipped；失败即已销毁 QListWidget 回调；跳过的是未启用的额外原生验收。日志：`build/ui-audit-20261029/regression.log`。
- 诊断探针：三个行为确认断言通过（慢 I/O、失焦拖动、外观预览），生命周期探针再次抛出上述异常。日志和脚本：`build/ui-audit-20261029/probes.log`、`test_audit_probes.py`。探针用于证实缺陷，不能作为功能正常的通过结果。
- 外观修改前后截图：`build/ui-audit-20261029/corner-before.png`、`corner-after.png`。
- `git diff --check` 通过。

## 修复与复验

上述四项已修复：

- 收藏关闭按钮的延迟定位改用对话框持有的单次 QTimer，隐藏时停止，销毁时自动释放。
- 收藏管理表监听所属窗口的 WindowDeactivate 和视口的 UngrabMouse；失焦后停止自动滚动并取消提交。下一次拖动清除上次的取消状态。
- 界面添加/替换收藏改走异步目录检查，显示“正在检查目录…”并禁用重复请求。后台线程不捕获 QObject；主线程重新检查重复项、数量上限和目标 ID 后保存。关闭对话框取消请求，序号不匹配的迟到结果丢弃。原同步内部接口保留兼容。
- 四角示例值使用配置中的字号、行距和颜色。行高及插入位置共用动态尺寸，避免显示变大后拖动落点偏移；编辑标签和操作按钮保留固定可操作尺寸。

新增 `tests/test_ui_audit_regressions.py`，四个原始回归先全部失败，再修复通过。补充了异步验证期间关闭、迟到结果、重复提交、目标被删除、出现重复目录、目录失效和写入失败的验证。实际鼠标操作覆盖失焦取消、关闭销毁及大字号下拖动；截图检查了修改后的预览。

扩展回归最终结果：**186 passed、3 skipped**，原失败已消除。跳过的是未启用的额外原生验收，另有三个既有 SWIG 弃用警告。日志：`build/ui-audit-20261029/fixes-regression.log`；修复后截图：`build/ui-audit-20261029/fixed-ui/`。`git diff --check` 通过。未进行 Windows 原生验收、打包或发布。
