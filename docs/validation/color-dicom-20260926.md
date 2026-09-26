# 彩色 DICOM 与导入目录切换验证

日期：2026-09-26。源码验证，未打包、发布或上传影像。

## 修改范围

- 导入对话框使用当前目录的平面表格，避免原有 `QTreeView.setRootIndex` 引发的无障碍缓存释放崩溃路径。保留目录跳转、文件/文件夹混选、排序、目录变更刷新及主题适配；排序保留选择，刷新保留正在输入的路径。
- 共用源颜色转换：RGB、解码器已转换的 YBR、PALETTE COLOR。调色板先映射颜色，不再将索引作为灰度强度。窗宽窗位、反白和伪彩不改变这些源颜色。
- 普通彩色多帧按帧索引读取，支持二维、平铺和已有播放功能。工作区保留实例/帧身份；报告使用测量所在帧的源颜色。
- 彩色图像不提供标量测量样本；隐藏 HU/SUV/MTF/FWHM/QA、灰度窗值等不适用工具。物理尺寸测量及毫米标尺要求有效 PixelSpacing，缺失时采用仅用于显示的单位像素网格。
- 彩色体数据明确拒绝 MPR/3D。切换多视口时重新应用当前序列的工具能力。
- 更新中英文操作手册的支持范围。

## 自动验证

最终相关回归：13 个测试文件，150 项通过，0 失败、0 跳过。

运行方式：

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python tests/run_isolated.py \
  tests/test_color_dicom.py tests/test_import_ui.py tests/test_pixel_codecs.py \
  tests/test_montage_rendering.py tests/test_workspace_persistence.py \
  tests/test_workspace_tool_selection.py tests/test_measurement_results.py \
  tests/test_two_d_layout.py tests/test_compare_2d.py tests/test_display_mapping.py \
  tests/test_theme_ui.py tests/test_manual.py tests/test_manual_site.py \
  --output build/color-dicom/final-regression
```

重点包括：红绿/蓝色已知像素、YBR 转换、8/16 位调色板、平面 RGB、JPEG Baseline/Lossless、两帧往返读取、平铺、旧显示参数隔离、工作区帧与测量恢复、彩色报告配图，以及彩色/灰度混合布局的工具切换。

目录测试访问 Qt 无障碍子节点后连续导航 20 次，并验证按大小排序后仍选中原文件。

## 原生 macOS 检查

在隔离配置的源码应用中，通过原生 UI 工具操作并读取无障碍树：

- 初版平面列表完成 9 次目录切换；最终采用的惰性目录模型在另外两个独立进程分别完成 12 次切换，均未崩溃。
- 最后一个进程运行最终源码。交替进入包含 104 个文件的目录与彩色测试目录，检查路径、可见文件列表及应用仍可响应。
- RGB 两帧画面分别显示红/绿与蓝色，界面帧号与稳定后的控制器帧身份一致；播放和停止正常，图像版本持续更新。
- 实际打开 pydicom 自带的 JPEG Lossless RGB 样例，主视口显示源彩条，替代之前的不支持提示。
- 无标定彩色图像不显示毫米标尺及物理测量入口；带 PixelSpacing 的样例保留这些功能。灰度窗值及服务分析入口不出现在彩色视口。

Qt/macOS 无障碍树偶尔未枚举全部可见表格单元或退出对话框按钮；实际截图内容正常。这里确认的是原先目录切换崩溃路径不再触发，并非全面验收 Qt 无障碍实现。

## 边界

- 原生验证覆盖 macOS 源码运行；Windows 发行包未在本轮验证。
- 视频编码、大型病理切片、MR Color 专用对象和超声区域专用标定未扩展。
- 保持现有匿名导出检查；不会因新增彩色支持而绕过烧录信息检查。
- 未引入新的运行依赖，未修改 MTF/FWHM 公式。
