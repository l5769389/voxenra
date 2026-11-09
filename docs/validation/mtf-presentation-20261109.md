# MTF 结果、提示与保存链路

## 范围

落实两处讨论中的结果呈现方案。背景估计、积分权重、FFT 和首次下降交点的数值定义保持现状；算法稳健性由另一个线程研究，确认后再接入。此次修改不能作为算法精度提高的证据。2.5.0 发布须等算法方案合入后的完整验收。

## 行为

- 默认计算得到的有限数值与原曲线保留。敏感性超限仅提示；对照异常不清空默认计算，也不影响其他成功对照。
- 无交点仍为“未达到”；默认计算无法归一化仍报错。提示不据此断言影像不合格。
- 实测值旁逐项显示警告。高斯等效的 MTF50 只继承实测 MTF10 的敏感性；实测 MTF50 敏感时另行说明当前显示的是模型值。
- 普通自动取样和交点规则放入中性“计算详情”，重要提醒直接可见。
- 设置 → 服务工具 → MTF → 高级提示设置，默认 20%，可设 1–100%。这是工程提示阈值，不是误差或合格标准。
- 阈值和对照数据随结果保存；设置变化不改写历史结果，重新计算才采用新设置。老工作区中已被删除的数值不伪造恢复。
- 按最新要求，图像结果只保留尺寸、指标和实测/模型/拟合来源；处理敏感、检查未完成和对照无交点的提醒保留在右侧面板，完整对照保存在工作区。
- 旧文件或未来算法提供的未知对照名称安全显示，非法阈值及异常对照数据拒绝载入。

## 验证

- 最终相关回归覆盖数值、控制器、QML、设置、工作区、语言、帮助、导出和发布说明：12 个测试文件，共 334 项通过，无失败或跳过。
- Cocoa 原生 UI：7 项通过，包含敏感数值、显式重新计算、精确 ROI 和高级提示阈值。
- 截图复核后将英文目标标签精简为 Target，避免单词拆行；再次执行全部 MTF 原生 QML 测试 22 项通过，语言回归 31 项通过。
- 使用用户指定第 26 张的原始像素，10 mm ROI：第二点 Y 实测 MTF50 = 15.3280 lp/cm，最大参数变化 63.6%；第三点 = 11.0839 lp/cm，变化 31.6%。默认频谱值未改。
- 第一点 X559/Y433 仍无法归一化，未人为生成数值。
- 原生窗口通过精确 ROI 对话框输入第二点的局部坐标，检查中/英文实测与模型结果、计算详情、窄面板及记录往返。匿名测试元数据替换真实 DICOM 头信息。
- 两组去除 DICOM 头的模体数据各进行 150 个 ROI 大小/位置对照；独立 Fourier 求和与 FFT 曲线差异小于 5e-15。此项仅验证数值实现保持一致，不验证背景估计或归一化的物理正确性。
- 本地记录：`build/mtf-sensitivity/verified/results.json`、`real-results.json`、`phantoms/final-results.json`、`media/`；原生测试日志 `build/mtf-sensitivity-native-final.log` 和 `build/mtf-sensitivity/native-mtf-final.log`。

## 原生界面截图

使用源图像像素和匿名测试元数据，在 QQuick 测试窗口中完成操作；截图不是发布包验收。

- [实测结果及逐项提醒](../../build/mtf-sensitivity/media/measured-zh-CN.png)
- [模型来源及实测值复核提醒](../../build/mtf-sensitivity/media/equivalent-en-US.png)
- [计算详情与对照值](../../build/mtf-sensitivity/media/details-zh-CN.png)

## 后续：精简图像标签及隔离绘制状态

- 用户确认问题发生在画新框期间：旧框和新框的指标一起变化。原 `MeasurementLayer` 将同一份当前标签传给所有 ROI；MTF 与 FWHM 都已通过原生鼠标事件复现。
- 标签改为按 ROI ID 读取。旧框使用其已提交几何与结果；新框只显示自身几何；编辑原框时暂不显示旧分析值。取消新绘制保留原结果，完成后沿用每帧一个分析 ROI 的替换规则。
- 按用户要求移除影像标签中的警告图标、提示阈值及复核文字，包括图像导出；右侧面板与计算详情仍保留诊断信息。
- 回归：9 个测试文件、244 项通过；Cocoa 原生 6 项通过，覆盖新建、拖动、取消、完成、编辑、MTF/FWHM 标签及敏感指标。
- 记录：`build/mtf-label-isolation/regression/results.json`、`native.log`。截图：[MTF 绘制隔离](../../build/mtf-label-isolation/native/test_new_analysis_draft_keeps_0/mtf-independent-draft.png)、[FWHM 绘制隔离](../../build/mtf-label-isolation/native/test_new_analysis_draft_keeps_1/fwhm-independent-draft.png)。

## 后续算法接入约定

1. `MtfAxisResult.sensitivity` 是 `MtfSensitivitySample(variant, mtf50, mtf10, error)` 的元组。频率保持 lp/mm；对照失败使用 `error`，成功但无交点使用 `None` 且 `error` 为空。
2. `BeadMtfResult.sensitivity_threshold` 保存本次提示阈值，`notes` 保存普通说明，`warnings` 保存其他重要质量提醒。原始数值不得因提示超限而置空。
3. `unreliable_metrics` 仅保留旧文件无法恢复的指标；新敏感值使用结构化对照数据。
4. `MtfRequest.sensitivity_threshold` 在提交后台任务时固定。当前结果记录算法版本为 2（诊断与呈现行为更新），不代表数值内核改进；替换内核时需再更新版本并保留历史结果。
5. UI 由 `core/mtf_quality.py` 推导提示；单位切换同时缩放默认值与对照值，百分比不变。增加新对照类型时须添加相应中英文 `mtf.variant.*` 名称。
6. 等新算法完成后，联合验证已知真值、真实样本、旧/新工作区、异步任务、模型派生及导出，再准备最终发布提交。
