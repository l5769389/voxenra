# 空间与数值专项验证（2026-09-28）

## 结论与范围

本轮代码基线为 `6e6af6a`，产品源码版本 **Voxenra 1.8.0**，对照软件为本地 **Slicer 5.12.4**。
新增可重复的合成案例、真实文件适配器、Slicer DICOM 采集器、分割往返与跨进程工作区测试。
**发现并修复 1 项测量输入错误；尚不能宣布整个专项验收完成。** 原生双软件 UI 对照受应用访问权限阻挡，另有明确不支持及无法直接比较的场景。

- 56 个输入案例：34 个合成案例、13 组真实数据、9 个编码／未压缩参考案例。压缩与参考文件可能表示相同影像，不等同于 56 个独立临床数据集。
- Voxenra：44 个案例完成其可用路径检查，12 个合成异常／不支持案例正确拒绝体重建，同时验证可读取的二维帧。
- Slicer：34 个案例完成同网格体数据或同平面二维比较；8 个案例有解释／分组差异；2 个案例无法完成空间对照。另记录上述 12 个不支持案例在 Slicer 中的行为，不算直接体素对照通过。
- 23 个分割交换组完成 **Voxenra → Slicer → Voxenra**；重叠、空分割及二值掩膜保持一致。
- 19 个相关测试文件：**266 通过、6 跳过、0 失败**。6 项跳过需要原生桌面／OpenGL，不计为可见 UI 通过。最终新增合成与进程重启测试再次运行，**37 项通过**（与前述数量有重叠，不累加）。
- 全量回归覆盖 **167 个测试文件、2407 项测试**。首次发现 1 项 MTF 校准错误提示回归，修正后重跑 10 个受影响文件，**229 项全部通过**；按各文件最后一次运行汇总为 **2336 通过、71 跳过、0 个未解决失败**。71 项跳过包含未配置真实样本／PACS、原生桌面及 OpenGL 依赖；本地真实样本已另行运行，不将跳过计为通过。

机器可读、去除原始身份元数据的汇总：[spatial-numeric-20260928.json](spatial-numeric-20260928.json)。
完整输入清单、SHA-256、逐案例结果、Slicer 警告、矩阵、像素及分割往返文件保存在本地 `build/spatial-audit/`，不加入 Git。

## 覆盖矩阵

| 路径／条件 | 独立核对 | Slicer 核对 | 结论 |
| --- | --- | --- | --- |
| 轴／冠／矢采集、反向轴、非零负原点、复合斜位 | 生成前定义的 LPS 仿射、标志点及非对称强度场 | 原始 DICOM 直接导入，统一为 `(slice,row,column)` 与 LPS | 通过 |
| 各向异性、非方形像素、1 mm 层厚配 5 mm 等距采样 | 长度、面积、体积采用真实间距 | 矩阵／体素一致 | 通过；均匀层间空隙未误判为缺层 |
| 文件乱序、InstanceNumber 逆序、重复输入文件 | 来源路径／帧／SOP 身份、存储像素、物理层序 | 几何排序后比较 | 通过 |
| 经典逐层缩放、负 HU、小数 slope/intercept | 原始值按独立公式转换 | 同网格数值比较 | 通过 |
| Enhanced CT 逐帧缩放、双时相交错 | 18 帧拆成两个 9 层组；各帧独立转换 | 默认标量插件合并时相；逐帧 slope 案例有不同解释 | Voxenra 通过独立真值；Slicer 差异单列 |
| MONOCHROME1、Padding、改变窗值及反白 | 显示操作不改变定量值；Padding 不参与统计 | GDCM 对 MONOCHROME1 作像素补码；Padding 保留数值 | 定义差异，未据此修改 Voxenra 定量像素 |
| 重复位置、非等距、单层漂移、均匀剪切、方向冲突、非正交方向、缺失／0／NaN 间距、缺位置、混合参考系 | 逐帧可解码，规则体重建必须拒绝 | 记录自动修正变换、警告或默认几何 | 明确不支持，未静默拼成规则体 |
| 同一经典 CT Series 内交错两个时相 | 源帧可读取；重复位置阻止三维构建 | 默认标量加载亦不能作为正确分组真值 | **现有限制：不拆组，不提供该输入的 4D** |
| 跨 Series 的经典 CT 4D | 既有分组、切换、工具、QML 回归 | 本轮未作成对原生 UI 检查 | 自动回归通过；原生 UI 未验证 |
| P113、HFS／HFDR 厚层 MR、薄层 MR | DICOM 原始标签；MR 另核对固定上游 NIfTI 参考的存储值与坐标 | 原始 DICOM 直接导入 | 通过 |
| Philips 幅度／相位、双回波四时相、Canon 13 扩散组、Siemens 四时相 | 928 个源帧／29 组；标准逐帧 Rescale、方向及上游参考 | Philips／Canon 默认标量插件合并维度；Siemens 所选加载失败 | 独立核对通过；Slicer 不能直接裁决分组 |
| NEMA Enhanced CT HU | 原始帧、HU、逐帧几何 | 直接导入逐体素与矩阵 | 通过 |
| 非 HU 派生灌注图 | 原始像素及单位 `ml/100ml/s`；体重建保持限制 | 缺少可直接对比的规则体几何／定量解释 | 二维路径通过；不冒充 HU 或三维验收 |
| PET BQML／SUVbw、GML、跨午夜、缺体重／剂量 | 独立剂量衰变公式；缺条件保持源单位 | 同网格源活度数值；**未验证 Slicer SUV 换算** | 独立公式通过，Slicer 量化项未完成 |
| RLE、JPEG-LS、JPEG 2000 无损及未压缩参考 | 5 对文件按固定 SHA 核对；存储像素完全相同 | 8 个同平面案例通过 | 通过所列样本，不推广到所有传输语法 |
| JPEG Lossless 灰度样本 | 实际扫描／解码；两软件帧像素相同 | 原文件缺患者平面信息，无法核对患者坐标 | 数值相同，空间受阻 |
| 三方向 MPR、平面内旋转、独立复合斜切、4 类投影 | 207 个平面，828 组投影；独立八邻域插值与固定采样归约 | 本轮未直接比较 Slicer 任意平面／厚层输出像素 | 独立解析核对通过；不宣称 Slicer 该项通过 |
| 长度、角度、矩形、椭圆、直边自由形状、跨边界 ROI | 解析几何；逐像素中心包含；总体 SD | Slicer Markups 长度及 Segment Statistics（样本 SD 按定义核对） | 数值通过；平滑自由形状本轮未新增独立栅格化对照 |
| 重叠／空分割、名称／颜色、掩膜与体积 | 掩膜精确计数、有限像素统计、体素体积 | 23 组 NRRD 往返与统计 | 通过 |
| 保存后进程退出再恢复 | 普通 CT／复合斜位／Enhanced 双时相，帧身份、切片、像素、长度 | 不适用 | 3 组通过；另运行既有工作区／结果定位回归 |

## 关键数值与差异

### 空间与插值

真实样本相对原始 DICOM 标签的最大已测标志点误差约 **0.0000952 mm**，小于 `0.001 mm`。
体素顺序、方向和标志点另作离散判断，不以容差掩盖轴交换或左右翻转。
MPR 显式验证轴／冠／矢的显示方向，再以独立真值仿射反求源坐标；不是只验证内部矩阵互逆。
有效点、无效点、边界点分别记录。投影固定厚度、采样偏移及 max/min/mean/sum 定义。

强度判断使用 `atol=1e-4, rtol=1e-6`，插值使用 `atol=1e-4, rtol=5e-6`。
JSON 中绝对误差不是单独的通过阈值：例如本地 PET 的大数值源活度浮点转换绝对误差约 `0.1232`，仍满足指定相对误差；不能据此放宽其他样本容差。
本地 PET SUVbw 独立公式相对产品结果的最大绝对误差约 `5.87e-7`；仅验证采用标签中提供的体重、剂量、时间及半衰期计算，不证明源标签本身的临床准确性。

### Slicer 不是唯一裁决者

1. **MONOCHROME1**：本轮 Slicer/GDCM 输出等于有符号存储值补码后再缩放；Voxenra 保留原始定量值，仅反转显示。DICOM 将该属性定义为 VOI 之后的显示极性，因此不应通过改动测量值去追随此差异。[DICOM Image Pixel](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.3.html)
2. **Enhanced CT 逐帧缩放**：本轮 RLE 案例中 Slicer/GDCM 将首帧 slope 用于所有帧；Voxenra 与逐帧标签及生成前真值一致。本结论限定到此加载路径，不声称所有 Slicer 读取器相同。
3. **多维 Enhanced 数据**：标量体加载路径可合并不同回波／时间／扩散维度。这些结果不符合本次相同分组、相同网格的逐体素比较条件。没有另装扩展或把合并后的网格当作真值。
4. **异常几何**：Slicer 在部分非等距／剪切案例建立 GridTransform，另有缺标签案例采用默认几何；记录修正，不直接比较不同网格。其插件机制与几何处理也见 [Slicer DICOM 文档](https://slicer.readthedocs.io/en/latest/user_guide/modules/dicom.html)。

坐标解释采用像素中心、LPS、PixelSpacing 的行／列顺序及 IOP 的方向定义。[DICOM Image Plane](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)

### 已修复：未校准二维网格被用于毫米测量

灰度 DICOM 缺少 PixelSpacing 时，Stack 使用 `(1,1)` 像素网格以便显示；原测量入口直接接收这份显示几何，可能将 10 像素误标成 10 mm。0 或 NaN 间距也没有在这个入口统一拦截。
现在按**当前来源帧的有效间距**控制长度、角度、ROI、曲线的创建与粘贴，右侧面板和收起模式快捷按钮同步禁用，显示中英文原因。二维查看及箭头／文字标注仍可使用。翻页后重新判断，不把上一帧的校准状态带入当前帧。
MTF/FWHM 保留各自已有的原始间距校验：仍可框选并显示像素面积，但缺少间距时报告错误、不计算物理频率／宽度。首次全量回归发现通用拦截遮蔽了 MTF 原有错误提示，已缩小拦截范围并复测相关工具。

修复前 `tests/test_spatial_missing_calibration.py` 的 3 个异常间距案例失败；修复后 4 项通过，新增正常 → 未校准 → 正常切片切换验证。中英文、浅色／深灰、小窗口 QML 渲染及状态同时核对；截图在本地 `build/spatial-audit/qml/`，这些是离屏 Qt 测试截图，不冒充原生桌面对照。

### 测试修正与产品修改边界

- 修正旧 Mosaic 手工回归的过期断言：现在允许创建错误页签，显示原因和关闭按钮，并禁止 PNG；无有效时相时 4D 入口仍不可用。原断言错误地要求阻止创建全部视图。
- JPEG-LL 与 `JPEG2000_UNC` 虽属于相同来源序列，后者标签标记已有有损处理、SOP 不同，不能当作前者的无损真值。本轮未放宽容差，而是排除错误配对，保留 JPEG-LL 与 Slicer 的原帧数值比较及空间限制。
- 产品修复仅增加测量校准保护与界面说明；**未修改几何重建、解码、统计、MTF/FWHM 公式、工作区格式**，未引入自动重采样。同步补充中英文操作手册。

## 原生界面与未完成项

本轮重试后，`Voxenra Spatial QA` 应用访问权限已恢复，已在隔离设置中完成以下原生操作，并核对可见界面与只读状态记录：

- **复合斜位测量**：打开预先生成的工作区，像素间距为行 `0.7`、列 `0.5 mm`；端点 `(0.5,1.5)` → `(10.5,9.5)`，解析长度 `7.507329751649384 mm`，视口和列表均显示 `7.51 mm`。测量本身由测试夹具生成，不计为鼠标绘制验收。
- **显示变换与定位**：通过原生按钮顺时针旋转 `90°`、水平镜像，测量值不变；跳到第 8 张后点击测量结果，回到第 5 张及原 SOP 实例。
- **保存重启**：通过界面保存、退出、重新启动并打开工作区；切片、SOP、像素 SHA-256、测量端点、长度、窗值、旋转与镜像全部一致，恢复到“测量 → 长度”，播放暂停。旋转后光标 `(12,9,4)` 读数 `-952.5 HU` 与解析真值一致。
- **不规则数据限制**：通过文件夹选择器导入 `invalid-nonuniform`，可打开二维页签；MPR 创建错误页签，明确提示不支持重复位置、不等距或层间偏移，仅提供“关闭页签”，体数据操作禁用。

Slicer 原生 Volume Information 与解析真值一致：尺寸 `(23,17,9)`、间距 `(0.5,0.7,2.4) mm`、RAS 原点 `(31.25,-17.75,-12.5) mm`、强度范围 `[-1084,-173.5]`；界面方向矩阵最大误差 `1.11e-16`。Data Probe 的 IJK `(13,6,4)`、第 5 层、值 `-961.5` 与独立真值相同。两款软件此次光标位置不同，不能算“同一患者坐标导航”验收通过。

本地证据位于 `build/spatial-audit/native/ui-observation.json`、`voxenra-restart-observation.json` 和 `acceptance-summary.json`；原生截图在本轮 CUA 操作记录中。测试夹具仅定时写出只读状态，没有新增产品控制入口。

**仍受阻的操作**：CUA 坐标点击／拖拽反复返回 `windowNotFoundAtPosition`；可访问性按钮和文件对话框可操作。未将该工具错误判为产品绘图问题，也未通过其他自动化方式绕过。Slicer 长度标注没有形成可确认端点，不计为通过。

**待补验收项**：普通 CT、HFDR MR、Enhanced 多帧／时相、PET/CT 的成对原生截图及同一患者坐标导航；定位线、鼠标绘制／控制点拖动、缩放后测量及快速时相切换。Qt 集成测试与数值脚本不能代替这些可见检查。

已确证的未校准测量错误已修复，本轮新增原生检查未发现新的空间或数值错误；未完成界面覆盖、Slicer 加载差异、同 Series 多时相限制及第三方插值／SUV 未核对项仍须保留，不能被其他测试通过抵消。

## 复跑方式

先安装项目开发依赖。所有生成数据和原始样本只放本地输出目录。

```sh
# 常规 CI：不依赖真实样本和 Slicer；包含两个独立进程的保存／恢复。
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_spatial_numeric_audit.py -q

# 生成解析真值并走实际扫描、解码、重建与交换入口。
PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m spatial_audit --output build/spatial-audit/synthetic

# 本地真实样本清单格式见下文；不下载、不修改输入文件。
PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m spatial_audit.real local-manifest.json build/spatial-audit/real

# macOS：独立偏好与逐案例临时 DICOM 数据库；只读取原始 DICOM。
CFFIXED_USER_HOME="$PWD/build/spatial-audit/slicer-home" \
VOXENRA_SPATIAL_AUDIT="$PWD/build/spatial-audit/synthetic" \
/Applications/Slicer.app/Contents/MacOS/Slicer --no-splash --no-main-window \
  --python-script "$PWD/tests/manual/collect_spatial_slicer.py"

# real / codecs 输出目录可按同样方法交给 Slicer。随后比较和分割回读：
PYTHONPATH=src:tests .venv/bin/python -m spatial_audit.compare build/spatial-audit/synthetic
```

`local-manifest.json` 为列表，各项包含 `name`、原文件绝对路径列表 `paths`、可选 `expected_groups` 和 `provenance`。
示例：`[{"name":"local-ct","paths":["/local/image1.dcm","/local/image2.dcm"],"expected_groups":1,"provenance":"local source record"}]`。
适配器保存逐文件 SHA-256；公开样本固定上游版本与许可沿用已有本地 manifest 及 `docs/mr-test-data.md`、`docs/enhanced-ct-test-data.md`，外部样本测试再次核对固定哈希。P113/PET-CT 是用户本地原件，未声称有可再分发许可。

真实样本测试用 `VOXENRA_MR_SAMPLE_DIR`、`VOXENRA_ENHANCED_CT_SAMPLE_DIR`、`VOXENRA_COMPRESSED_SAMPLE_DIR` 明确传入位置；没有依赖时跳过。Slicer 独立采集器必须显式运行，缺结果时比较报告标为 `blocked`。
本地专项回归日志位于 `build/spatial-audit/acceptance/`；完整回归及修复后重跑分别位于 `build/spatial-audit/full-regression/`、`build/spatial-audit/final-affected/`，保留首次失败记录。数据、数据库、截图及工作区不加入产品包、README 或首页。
