# 2026-10-30 UI 审核修复复验

对应原审核 `audit-20261030-ui-toast.md` 与 `cpr-focused-audit-20261030-ui.md`。本轮修改业务 QML 与回归测试，不提交、打包或发布。

- CPR-UI-01 / CPR-UI-02：先新增真实 QTest 键盘回归，旧实现分别失败于 `12.3 != 12.34`、清空移焦仍为空。改用现有 `AppNumberField`，统一两位小数、Enter 后移焦不重复提交、无效移焦恢复实际模型。回归比较字段、模型及已接受曲面参数。Cocoa 原生完整 Main 探针的 Enter / blur 三者均为 12.34；空值移焦恢复 12.34，无 QML warning，已查看截图。
- UI-05：四个结果状态通过 `qsTrId` 翻译，英语/中文/葡语目录由主修复任务统一补齐。
- UI-06：复用通用导出交互，加入延迟进度、取消、结果路径和定位操作。QML 状态替身测试验证忙碌时进度值、点击取消调用、完成路径及定位调用；不将替身测试称为慢磁盘实测。
- UI-07：融合选择器按比较选择器模式，在活动原生 volume 或 MPR quad（包括2D焦点）上开启 `Popup.Window`，固定原生隐式尺寸 780×640，关闭重复自绘关闭按钮。两项原生 Cocoa＋VTK 测试（3D、MPR quad焦点在2D）同时检查窗口、候选列表可见高度、取消后仍在原3D/MPR页签、选择确认后真实融合页签加载完成及无 QML warning。屏幕截图已人工查看：标题、候选序列、取消和融合按钮均完整覆盖在 VTK 上方。首次原生截图发现仅指定 width/height 会让原生弹窗以内容隐式高度缩短、候选列表被挤空，故补上与比较器一致的 implicitWidth/implicitHeight 并回归；不以 accepted/click 成功单独判定通过。
- UI-08：插入位置计算使用一次 tabs 快照及边界，宽度计算允许空项。回归直接模拟清空后残留索引15，偏移返回0且没有 `tabType of undefined`。未重新恢复原审核的完整15页签文件。
- UI-04：保留验收缺口。ROI入口继承 Basic.Button 的文本可访问名称，源码没有主动忽略子项；原审核已显式限制为 macOS AX 输出不完整，尚无确定代码根因。本轮没有以加属性或更换角色猜测修复，也未声称完成 VoiceOver/AX 全链路验收。

证据在本工作树 `build/audit-fixes-ui/`：`native-parameter.log`、`main-precision-after-enter.png`、`main-precision-after-blur.png`、`main-empty-after-blur.png`、`native-fusion-final.log`、`native-fusion-final/test_fusion_picker_above_nativ0/fusion-desktop-True.png`、`native-fusion-final/test_fusion_picker_above_nativ1/fusion-desktop-True.png`。原生参数探针由既有完整 Main 审核探针改为 Cocoa 运行，副本为 `main_probe.py`。

运行使用显式 `PYTHONPATH=src`、当前 `.venv/bin/python`；离屏使用 `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software`，原生使用 `QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software`。扩展组合首次75项中74通过，现有 CPR 完成按钮 Esc 后焦点断言失败一次，原样单独重跑通过；该时序现象已告知主任务，未修改断言掩盖。

最终针对字段、CPR页、融合选择器的离屏回归27通过、1原生项跳过（后续原生参数化新增MPR分支）；最终原生3D/MPR选择器2通过。`git diff --check`通过。
