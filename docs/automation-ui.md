# 精确操作与可读取界面

## 本轮修改计划与交付

1. 补齐页签、2D 视口、分析选项、曲线及结果的可访问性名称与状态。
2. 统一面向用户和辅助功能的切片编号，提供精确跳转。
3. 提供 MTF/FWHM 数值 ROI，复用鼠标绘制的提交及计算流程。
4. 用 Qt 界面操作、可访问性操作、控制器状态和截图联合验证。

本轮不增加网络服务或 MCP 服务。`stateSnapshot` 是进程内控制器属性，
不会自动成为 Codex 可调用的远程工具。后续若需要批处理，可围绕现有控制器
添加命令适配层，再单独定义任务完成状态、权限与版本兼容规则。

## 切片定位

- 滑块可访问名称为“切片编号”，其值与画面一致，从 **1** 开始。
- 点击滑块下方的当前编号，或访问“跳转切片”按钮，输入编号后按 Enter。
- 输入范围为 `1…切片总数`；底层 `setSliceIndex()` 仍使用从 0 开始的索引。
- `sliceControl`、`sliceJumpButton`、`sliceNumberInput` 是稳定的局部对象名。
  多视口情况下，应先定位所属页签和视口，不能把全局第一个同名控件当成目标。

## MTF / FWHM ROI

在对应服务面板点击“精确设置 ROI”：

- 中心 X/Y：**原始图像像素坐标，从 0 开始**，不受显示缩放或旋转影响。
- MTF：输入物理正方形的边长，单位 mm；各向异性像素下，像素宽高可以不同。
- FWHM：分别输入矩形的宽、高，单位 mm。
- 尺寸指几何边界间距，不是像素数量。计算沿用现有的像素中心包含规则。
- “应用并计算”或 Enter 一次提交全部参数。越界、非有限值、无有效物理间距、
  采样不足等输入不会覆盖现有 ROI/结果。MTF 每轴至少包含 8 个像素。
- 切片或当前 ROI 变化时，关闭旧编辑弹窗，避免把旧参数应用到新的图像。

相应对象名：`editAnalysisRoi`、`analysisRoiCenterX`、`analysisRoiCenterY`、
`analysisRoiWidth`、`analysisRoiHeight`、`applyAnalysisRoi`。
MTF 与 FWHM 的 ROI 和缓存相互独立。

## 读取和验证结果

选项和曲线按钮暴露名称及勾选状态；结果表暴露带方向、数值、单位的摘要。
实际计算方法单独可读，计算说明与质量提示仍收在信息按钮中。
2D 视口的可访问性描述包含切片、窗宽、窗位、加载状态和错误原因。

进程内 `mtfController.stateSnapshot` / `fwhmController.stateSnapshot` 提供：

- `frameToken`、`sliceNumber`、`roi`：当前帧身份及几何。
- `status`：`empty` / `editing` / `calculating` / `ready` / `error`。
- `measurementMethod`、`requestedMethod`、`actualMethod`：目标与算法。
- `frequencyUnit`、`result`、`warnings`、`error`：结果与质量信息。

只有 `ready` 才返回计算结果。进入编辑或切换到尚未加载的切片时，不展示旧结果；
被后续 ROI 替代的后台任务不能覆盖新结果。`ready` 表示数值计算完成，
不保证某个 GPU 帧已经显示。截图检查和真实桌面操作仍然必要。

## 回归验证

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  .venv/bin/python tests/run_isolated.py \
  tests/test_mtf_controller.py tests/test_mtf_qml.py tests/test_mr_qml.py \
  tests/test_measurement_controller.py tests/test_appearance_language.py \
  --output build/accessible-analysis/tests
```

测试覆盖数字跳转和实际图像切换、辅助功能增减操作、ROI 原子提交、无效输入、
异步结果乱序、结果可读性，以及宽/窄窗口的弹窗显示。
