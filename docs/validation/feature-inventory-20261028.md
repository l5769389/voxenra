# 功能目录核对（2026-10-28）

本次核对 README 中英文、手册专题和当前源码，覆盖完整产品目录及能力边界；不制作安装包或发布版本。源码基线为 `8adde47`，另包含工作区内工具栏可视化编辑与六类入口改动。标签 `v2.1.3` 指向 `db26265dfa15bcc476639d8988d81056c1cd8773`；该标签不含 DIMSE、阅片身份改进、工具栏自定义、窗模板收藏和视图区最大化。两份 README 均保留 v2.1.3 下载链接，并明确区分当前源码能力。

## 核对矩阵

“已有”指 v2.1.3 已有实现；“当前源码”指标签之后的实现或本地已验证改动。依据包含源码、测试及已有原生验证记录，本表本身不声称重新执行所有功能测试。

| 功能组 | 核对后的说明与边界 | 状态 | 主要依据 |
| --- | --- | --- | --- |
| 本地导入 | 文件／文件夹／压缩包混选与拖放、后台进度、取消、内容识别、去重；压缩归档与像素编码分开描述 | 已有 | [本地导入](../local-import.md)、`tests/test_local_import.py` |
| DICOMweb | QIDO-RS、WADO-RS、多配置、会话认证、完整校验后发布导入结果 | 已有 | [PACS](../pacs.md)、`pacs/client.py`、`pacs/importer.py` |
| DIMSE | C-ECHO、Study Root C-FIND、C-MOVE 与临时 C-STORE；需 PACS 登记回传节点，C-ECHO 不等于导入通过；不含 C-GET、TLS、上传、永久接收 | 当前源码 | `pacs/dimse_client.py`、`pacs/dimse_receiver.py`、[真实服务验证](dicom-dimse.md) |
| 2D 与多视口 | 原始／重建切面、调窗／反白／伪彩、6×6 布局、拖放、单视口放大、播放 | 已有 | `qml/assets/help/chapters/views.json`、`ui/controller/tab/tool_controller.py` |
| 2D 对比 | 2–4 序列、当前视口同步来源、患者空间／相对进度、定位线与 Alt＋单击；MR 默认独立调窗／反白，无自动配准 | 已有 | `ui/controller/tab/compare_tab_controller.py`、`core/compare.py` |
| MPR 与对比 | 七种布局、斜面、MIP/MinIP/Mean/Sum；位置／旋转增量联动、当前组 CT 调窗及物理比例同步、对应切面放大 | 已有 | `ui/controller/tab/compare_mpr_tab_controller.py`、`qml/assets/help/chapters/views.json` |
| 3D／4D | CT/MR/PET 体绘制、模板、裁剪、CT 去床板；经典 CT 有效时相播放，当前时相切片播放、分相位结果 | 已有 | [影像支持](../image-support.md)、[MPR 与 VOI](../mpr-segmentation-voi.md)、`model/tool_catalog.py` |
| PET／融合 | 条件化 SUV 或源单位、切面定量、手动刚性配准、融合比例和融合 3D；MIP 不作体素定量绘制 | 已有 | [PET 与融合](../pet-mpr-fusion.md)、[MPR 与 VOI](../mpr-segmentation-voi.md) |
| 测量／标注 | 六类测量、文字箭头、名称／锁定／显隐、复制粘贴、历史；自由形状为逐点平滑轮廓 | 已有 | `model/tool_catalog.py`、`tests/test_freehand_roi.py`、`qml/assets/help/chapters/measure.json` |
| 分割／交换 | CT/PET 阈值与球形／椭球 VOI；CT/MR/PET 精修管理、连通区域、重叠掩膜、SEG／NRRD；MR 不开放 CT/PET 阈值工具 | 已有 | [分割与 VOI](../mpr-segmentation-voi.md)、[影像支持](../image-support.md) |
| 本地 AI | TotalSegmentator 环境独立安装、CT 当前时相、器官选择、叠加／精修／保存；既有演示明确为模拟推理结果 | 已有 | `qml/assets/help/chapters/mpr-segmentation.json`、README 既有 AI 演示说明 |
| QA | 未检出水模时普通圆形 ROI、初始区域可删除、位置／副本／删除状态保留、重算与重新生成不同、撤销重做、条件化五点汇总 | 已有 | `core/water_qa.py`、`ui/controller/viewport/controller/water_qa_controller.py`、[ROI 验证](qa-roi-fallback-20261026.md)、[历史验证](workspace-retention-qa-history-20261026.md) |
| MTF／FWHM | 点源 MTF、斜坡 FWHM 与层厚；正式曲线、参数、ROI 及来源随工作区保留 | 已有 | `qml/assets/help/chapters/service.json`、[工作区](../workspaces.md) |
| 导出 | 源序列 PNG／DICOM 与视口 PNG 区分；测量 CSV／PDF 的来源平面参考图、SEG/SR、NRRD；匿名不清理像素烧录文字，SEG/SR 保留身份 | 已有 | [导出](../export.md)、`ui/report_reference_images.py`、`tests/test_measurement_report_pdf.py` |
| 工作区／多窗口 | 新建、保存、自动恢复、来源重定位、页签迁移、已关闭结果保留与重开；不复制源像素，不保存草稿／历史，新建影响整个工作区 | 已有 | `ui/controller/workspace_controller.py`、`workspace_document_controller.py`、[保留结果验证](workspace-retention-qa-history-20261026.md) |
| 阅片身份 | 日期／序列号／原始描述、悬停完整信息、重复来源区分、隐私隐藏 | 当前源码 | `ui/reading_identity.py`、`tests/test_reading_identity.py` |
| 窗模板收藏 | WW→WL、独立滚动、星标优先、收藏不应用窗值、持久保存 | 当前源码 | `ui/controller/settings_controller.py`、`tests/test_window_template_scroll.py` |
| 工具栏 | 六类入口与细分配置、整块图标拖动／跨组、键盘操作、7 项上限、草稿／保存／取消／恢复当前默认 | 当前源码 | `ui/controller/toolbar_settings_controller.py`、[分类验证](toolbar-categories.md)、[可视化验证](toolbar-visual-editor.md) |
| 视图区最大化 | 页签栏按钮／F12，隐藏全部侧栏，恢复宽度和折叠状态；窗口局部，与单视口放大／系统全屏独立 | 当前源码 | `tests/test_viewport_maximize.py`、`qml/sections/center/CenterPanel.qml` |
| 外观与帮助 | 三主题、输入／快捷键、文字标签、显示叠加、JSON 语言／窗模板、离线动画、反馈、更新 | 已有 | `qml/assets/help/chapters/settings.json`、[手册](../manual.md) |

源码简写均相对于 `src/qt_dicom_viewer/`。

## 修正的旧说明

- README 遗漏 DIMSE、阅片身份、工具栏配置、窗模板收藏、整片阅片区最大化；补全既有 2–4 对比、当前视口同步、CT 去床板、QA 编辑及导出范围。
- 英文 README 原句 “conventional and Enhanced CT/MR/PET” 会把 Enhanced PET 误列为支持；改为常规 CT/MR、经典静态／全身 PET、Enhanced CT/MR，并明确 Enhanced PET 不支持。
- `docs/workspaces.md` 仍声称关闭页签须破坏性确认且不进入后续保存，现与已关闭结果保留、重开入口及新建工作区一致；同步逐点自由形状和 PDF 来源平面描述。
- `docs/water-qa.md` 仍声称初始五区不能删除且重新分析恢复布局，现明确普通 ROI 模式、删除／移动／复制、重算保留布局、重生成替换布局及撤销重做。

## 文档验证与演示边界

- 上述 README 和专题文档的差异空白检查通过；两份 README 各 75 个引用已分类检查，相对路径目标全部存在、各 6 个 HTML 表格结构闭合；专题与核对文档的相对链接也全部存在（未在本轮请求外网 URL）；中英文关键能力和版本标记检查通过。
- README 引用 DIMSE、工具栏、最大化及收藏的 `51`–`55` 中英文资源，静态检查已确认十个文件全部存在；演示的原生界面和操作结果状态由本次主任务单独验收。
- DIMSE 使用合成 DICOM 与本机真实服务；既有 AI 动画使用模拟推理输出。两类演示说明不同，不将 UI 流程表现当作模型准确度或临床性能证明。
- 本次范围是文档核对，不扩展格式／协议兼容承诺，不声称重新完成 Windows 或医院厂商 PACS 验收。
