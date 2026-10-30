# 平面内自由旋转实施计划

> **For agentic workers:** Use superpowers:executing-plans to implement the tasks below. 用户已明确要求在 main 实施，不另建工作树、不发布版本。

**Goal:** 点击旋转启用平面内拖动旋转；90° 和镜像子项每次点击执行一次，保留当前旋转工具。

**Architecture:** 在现有拖动操作链增加 RotationOperation，更新已有的 rotation_degrees 显示状态。2D、MPR 共用实现；MPR 自由旋转优先于十字线命中，不修改 MprState。沿用现有工作区序列化。

**Tech Stack:** Python、PySide6、Qt Quick、pytest。

**Spec:** 本对话中用户对 2D/MPR 平面内旋转、主按钮与子项行为的要求。完整文案使用“顺时针 90°／逆时针 90°”；窄栏方向由图标表达，文字明确标出 90°。

## Constraints / decisions

- 沿当前影像显示中心拖动旋转，屏幕顺时针为正；中心附近忽略不稳定角度。
- 子项不成为拖动模式，连续点击各执行一次；切换其他工具结束旋转模式。
- 图像、标注、十字线共用显示变换，保留原始测量和患者空间位置。
- 右键临时缩放、滚轮翻页和已有镜像仍有效；恢复旋转不重置 MPR 切面。
- 不更改版本号，不创建标签、安装包或 Release。

## Review focus

跨越 ±180°、穿过旋转中心、平移/缩放/镜像后的手势、MPR 十字线命中优先级、工作区重新打开后的角度与工具状态。

## Tasks

- [x] 添加失败回归：主按钮后拖动产生任意角度；子项仅增加一次 90°；MPR 切面/定位不变；保存恢复角度。
- [x] 在 model/interaction.py、model/ui_models.py、model/tool_catalog.py 及 viewport/operation/rotation_operation.py 增加旋转上下文、结果和操作。
- [x] 接入 image_2d_viewport_controller.py，匹配 CursorPolicy.js 的优先级；检查共享工具目录涉及的视图。
- [x] 更新中英文旋转文案及手册，检查紧凑栏文字是否完整。
- [x] 运行变换、MPR、测量、QA、工作区和工具栏相关测试；用真实 QML 鼠标事件及桌面界面联合验证。
- [x] 复核 diff、记录结果；修改保留于 main。

## 验证记录

- `build/rotation-regression/results.json`：18 文件，413 通过、1 跳过（既有 tooltip 首次显示定位测试要求原生桌面）。
- `build/rotation-extra/results.json`：平铺 QML、手册、主题/语言共 54 通过。
- `build/rotation-review-fix/results.json`：PET 定位、融合 UI、融合控制器、自由旋转共 68 通过（与上述记录存在重复）。
- macOS Cocoa 实窗：2D/MPR 展开与紧凑工具栏 4 项通过；MPR 非等距像素、镜像、37° 显示旋转后的十字线命中 8 项通过。
- 已人工查看实窗截图，完整文案和窄栏 90° 均可见，MPR 交叉线方向与画面一致。
- 独立复核发现 PET 定位点优先捕获与旋转模式冲突；已用失败→通过测试修复四种 PET/融合角色，并禁止旋转模式下 MIP 点击改变患者定位。其余已检查范围未发现重要问题。
- 合并去重后的相关用例：527 通过、1 跳过。未运行全仓库套件；未提交、推送、打标签或发布。
