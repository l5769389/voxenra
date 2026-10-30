# CPR 与 3D Slicer 交叉验证（2026-10-30）

结论：当前**手动折线路径 CPR**的坐标、重采样、垂直截面、物理测量、历史来源及工作区恢复通过本次验证。发现并修复一处角标语义问题：12 mm Mean 投影原先仍显示 `Thickness: 1 mm`，实际引用的是源 DICOM 层厚；现在分别显示 `CPR · Mean 12 mm` 和 `Source thk: 1 mm`。不能据此宣称已完成临床冠脉 CPR 或狭窄定量验证。

分支 `codex/cpr-reconstruction`，检查基线 `3f413c3`。本机 macOS、Slicer **5.12.4 / 4e21c19**、VTK **9.6.2**。没有发布或合并。

## 方法与独立性

- Voxenra 通过真实 DICOM 扫描器、VolumeManager、CPR 和 MPR 核心读取与重建；Slicer 进程不导入 Voxenra，使用自身 GDCM 读取同一批文件。
- LPS/RAS 显式转换。比较完整源体数据的 float32 SHA-256、维度和 IJK/KJI 患者坐标矩阵，不靠截图判断左右、前后、层间距是否正确。
- 使用 Slicer Linear Markups 曲线独立计算路径长度与弧长位置。普通点的切向通过 Slicer 曲线位置求导验证；转折点没有唯一切向，单独记录，不把切向平均与出段切向混为同一算法。
- 横向参考轴和旋转另用 VTK 旋转矩阵按已声明的折线约定计算，与产品的 Rodrigues 实现比较，同时检查正交性、单位长度和右手系。
- 使用 Slicer/VTK 的线性插值器，在明确的患者物理网格上独立采样；比较 Thin/MIP/Mean、首/中/末三个垂直截面及无效区域。投影在同一厚度、同一采样位置聚合。这一项验证采样与投影，不冒充两套 CPR 默认输出的直接逐像素相等。
- 另外实际运行 Slicer 内置 GeneralizedReformat 的 `ComputeStraighteningTransform`、`StraightenVolume`、`ProjectVolume`，为四条路径生成 CPR 体数据和平均投影，并在 Slicer 原生界面载入查看源影像、路径与重建卷。
- 实际鼠标操作在 Voxenra 新建横截面 ROI、保存工作区、退出和重新打开；再将保存的物理坐标送到 Slicer Markups 复算长度、面积和 ROI 像素统计。可见界面与进程内只读状态、实际保存文件共同作为证据。

Slicer 内置 CPR 默认采用不同的曲线采样、初始横向方向及 B-spline 体重采样；普通曲线还可以选择平滑类型。因此直接要求默认截图或输出数组相同是不成立的。[Slicer 对应版本实现](https://github.com/Slicer/Slicer/blob/4e21c19/Modules/Loadable/GeneralizedReformat/Logic/vtkSlicerGeneralizedReformatLogic.cxx)

## 数据与结果

全部是合成数据或 Slicer 公开样本，没有使用私有患者资料。公开 CTACardio 文件校验和、裁剪范围见 [数据来源记录](cpr-slicer-20261030/public-source.json)。心脏 CTA 中的路径为明确构造的几何测试路径，**不声称沿冠状动脉中心线**。

| 数据 | 体素数（KJI） | 重建组合 | 最大弧长误差 | 最大位置误差 | 最大曲面像素误差 |
|---|---|---:|---:|---:|---:|
| 原生操作使用的双管合成 CT、两条保存路径 | 96 × 160 × 160 | 8 | 0.00000187 mm | 0.00000310 mm | 0.007782 HU |
| 23°/37° 斜位、0.6/1.1/1.7 mm 各向异性、非共面路径 | 48 × 64 × 80 | 5 | 0.00000131 mm | 0.00000327 mm | 0.000153 HU |
| 公开心脏 CTA 中心裁剪、三维测试路径 | 120 × 220 × 220 | 4 | 0.00000034 mm | 0.00000100 mm | 0.004525 HU |

三组源像素 SHA-256 均一致；源坐标矩阵最大差为 `2.85e-14 mm` 以下。17 组重建、51 个首/中/末截面以及历史截面均通过预先设定的容差（最大像素差 0.1 HU、平均差 0.01 HU、位置/长度 0.00001 mm、方向 0.000001）。有效/无效像素掩膜差异为 **0**；宽视野边界用例包含 2093 个无效曲面像素，没有被误填为有效灰度。

| 实际保存的测量 | Voxenra | Slicer 换算为相同单位 | 绝对差 |
|---|---:|---:|---:|
| 历史截面长度 | 3.992957628485094 mm | 3.9929576284850943 mm | 4.44e-16 mm |
| 本次原生绘制的横截面矩形面积 | 59.310012135234935 mm² | 59.30996884248459 mm² | 0.0000433 mm² |
| ROI 纳入像素数 | 234 | 234 | 0 |
| ROI 平均值 | 385.71417355333637 HU | 385.7142313932761 HU | 0.0000579 HU |

ROI 标准差差值 0.0001262 HU，最小值差值 0.00000382 HU，最大值相同。Slicer 面积显示单位为 cm²，使用 `GetDisplayValue()` 与显示单位配对后转换；不能将基础值 `GetValue()` 再按显示单位重复缩放。[Slicer 测量单位接口](https://apidocs.slicer.org/main/classvtkMRMLMeasurement.html)

所有未取整结果、拐角处的差异及明确的成功标记保存在 [results.json](cpr-slicer-20261030/results.json)。Slicer Markups 曲线内部的浮点离散造成微米以下至数微米的差异；不影响上述判定。

## 操作与业务核验

| 环节 | 本次观察 |
|---|---|
| 同源影像与路径 | Slicer 三平面能显示相同双管数据与两条 LPS 路径，位置关系一致；已另生成完整 Slicer CPR 卷。 |
| 曲面与横截面测量边界 | 曲面图的长度、角度和 ROI 工具禁用；横截面启用。没有给非平面曲面图伪造均匀欧氏标尺。 |
| 历史来源 | 当前 `Right tube` 已为 r6；点击 r5 / 35.9 mm 的 3.99 mm 记录恢复原物理平面，并明确显示“历史测量平面”。不会把旧测量贴到新路径的新截面。 |
| ROI | 在该物理截面用鼠标绘制矩形，显示 8.89 × 6.67 mm、59.31 mm²；保存的精确尺寸、像素统计与 Slicer 独立计算一致。 |
| 保存/重启/恢复 | 实际写出工作区并读回校验；重启后两条路径、35° / Mean 12 mm 参数、长度、ROI 及历史来源均保留。 |
| 影像角标 | 修正后源层厚与投影厚度分开标注；参数等待重建期间角标仍描述屏幕上已接受的图像，完成后才切换。 |
| 取消、旧任务、导出 | 本次重新运行相关自动回归，含草稿/待重建禁导出、异步代际、取消、PNG 三种范围、保存恢复与测量来源；原生完整编辑/删除/撤销/快速操作证据沿用 [10 月 29 日验收](cpr-ui-20261029.md)，没有伪称本次全部重新手工操作。 |

证据：

- [曲面测量禁用](cpr-slicer-20261030/01-curved-measurements-disabled.png)
- [Slicer 同源影像和路径](cpr-slicer-20261030/02-slicer-source-paths.png)
- [历史测量定位](cpr-slicer-20261030/03-voxenra-history.png)、[只读状态](cpr-slicer-20261030/03-history-state.json)
- [新建横截面 ROI](cpr-slicer-20261030/04-cross-roi.png)、[只读状态](cpr-slicer-20261030/04-roi-state.json)
- [最终角标与恢复状态](cpr-slicer-20261030/06-final-overlay.png)、[只读状态](cpr-slicer-20261030/06-final-state.json)

## 发现与后续改进边界

1. **已修复：源层厚与投影厚度混淆。** 原显示可让用户把 1 mm 当成 Mean/MIP 的厚度。共享影像角标现在分别标识重建方式/厚度和源层厚，PNG 使用同一组件。回归先失败再通过，并完成原生重启验证。
2. **建议下一阶段优先增加显式的路径平滑与中心线校正。** 当前是手动折线，截面取出段切向；控制点少或拐角急时，截面方向会突然变化。此次故意编辑后的第一条路径最大转角约 84°，第二条约 20.6°。这符合当前约定，但不是成熟血管工作站的平滑中心线体验。不能静默改变既有路径：需要保存曲线类型、版本和重建参数，并使旧测量仍指向旧平面。
3. **真实血管业务尚需另外验收。** 本次没有验证真实冠脉中心线是否准确、病变边界、狭窄率或诊断效能，也未增加自动血管追踪。公开 CTA 的几何路径不能代替这些验证。MR 病例、Windows 和其他 DPI 亦未做此次原生交叉验证。

## 复现

脚本：[validate_cpr_slicer.py](../../tests/manual/validate_cpr_slicer.py)。原生操作保存的纯数据夹具：[cpr_slicer_native.json](../../tests/fixtures/cpr_slicer_native.json)，包含两条路径、长度和 ROI 的原始物理来源，不含影像或本机文件路径。没有原生临时目录时，脚本重建相同合成 CT；存在 `native-ui.voxworkspace` 时优先读取实际保存文件。

在仓库根目录执行：

```sh
export CPR_VALIDATION_ROOT="$PWD/build/cpr-slicer-validation"
# 可选：通过 Slicer 官方 SampleData 下载/校验公开 CTA；不执行则仅运行合成用例。
CPR_VALIDATION_STAGE=public /Applications/Slicer.app/Contents/MacOS/Slicer --no-main-window --ignore-slicerrc --python-script "$PWD/tests/manual/validate_cpr_slicer.py"
.venv/bin/python tests/manual/validate_cpr_slicer.py
CPR_VALIDATION_STAGE=slicer /Applications/Slicer.app/Contents/MacOS/Slicer --no-main-window --ignore-slicerrc --python-script "$PWD/tests/manual/validate_cpr_slicer.py"
CPR_VALIDATION_STAGE=check .venv/bin/python tests/manual/validate_cpr_slicer.py
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_cpr*.py tests/test_dicom_overlay.py
```

Slicer 阶段仅运行非交互计算并保存 `cpr-reference.mrb`，不脚本化操作可见 UI。脚本检查输入 manifest/结果数组摘要，失败不复用旧成功报告。场景可用 Slicer 的 Add Data 打开。Windows/Linux 需替换 Slicer 可执行路径。

最终定向回归 **123 passed**，见 [测试输出](cpr-slicer-20261030/tests.txt)。这不是本次全仓测试的声明；没有因历史基线失败而修改无关模块。
