# 显示映射

原来的一级“调窗”工具统一为“显示映射”。控制方式取决于数值域、调色板和视图类型；显示操作不改变原始数据、光标数值、ROI 统计或患者坐标。

| 数据／视图 | 控制方式 | 单位与边界 |
| --- | --- | --- |
| CT 灰度切片、MPR、4D | 窗宽／窗位、HU 预设、反白 | 继续使用原来的 DICOM 灰度窗口算法 |
| MR 灰度切片、MPR | 来源窗、自动窗、反白 | 保留来源单位；不套用 HU 预设 |
| PET 切片、MPR、融合 | 从 0 开始的显示范围、单位选择、色表 | 使用现有 PET 显示控制器；单位切换按比例转换范围，等待新单位的像素后提交 |
| 补充彩色 CT，例如 RCBF | 原始映射／自定义范围、色条、单位；折叠的灰度背景控制 | 自定义范围作用于有颜色且数值有效的像素；使用源色表，不改变灰度背景 |
| 非 HU 标量 CT | 原始映射／自定义数值范围 | 使用已解析的数值单位；未知单位显示 a.u. |
| CT／MR／PET 3D | 颜色与透明度传递函数、体绘制预设 | 保留现有三维控制器；不套用二维范围面板 |

## 操作

灌注图默认显示文件原有颜色和色条范围。选择“自定义范围”后，设置显示下限／上限，或在图像中拖动调整范围。选择“原始映射”可恢复源颜色；原始模式下拖动不会暗中调整灰度背景。需要改变灰度部分时，展开“灰度背景调整”。图像角落同步显示当前范围及单位。

新的范围状态按视口保存在工作区中。翻帧保持范围；如果帧的数值单位变化，自定义范围回退为原始映射。对比视图中的派生 CT 默认不联动窗口。非法范围、非有限值和零跨度不会提交。

完整源 DICOM 导出继续保留原始数据；逐帧 PNG 导出使用来源映射。需要保存自定义显示效果时，使用当前视图导出。

## 实现

- `model/display_mapping.py` 定义能力、范围意图和源调色板数值范围。`window`、`range`、`palette`、`transfer` 区分不同显示方式。
- PET 继续通过已有 `PetDisplayController` 管理单位转换、待提交状态和共享范围，避免影响 MPR、融合及三维流程。
- `core/display_mapping.py` 为即时预览与后台帧渲染提供同一个映射函数。灰度 VOI 使用 Rescale 域，测量使用数值域；源调色板按存储值解释，自定义调色板按数值范围重新索引。
- 补充彩色模式默认完全保留源 LUT。仅支持当前已经解析的显式 8/16 位 RGB LUT 和单个线性 RWVM；分段 LUT、多映射选择和非线性 RWVM 沿用现有支持边界。
- 面板类型通知与频繁的范围／布局通知分开，防止切换 PET 3D 和二维视图时选错面板或形成 QML 绑定循环。
- 工作区只保存范围、模式与单位，不保存像素数组或 LUT。旧工作区缺少该字段时默认使用原始映射。

补充彩色规则参见 [DICOM Pixel Presentation](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.16.2.html)。读取现成 RCBF 图不等于计算灌注参数。

## 验证

运行合成与界面回归：

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen uv run --group dev python -m pytest tests -q
```

使用文稿中现有的影像库运行原生验收：

```sh
VOXPLANE_TEST_DICOM_DIR="$HOME/Documents/test_dicom" \
VOXPLANE_MR_SAMPLE_DIR="$HOME/Documents/test_dicom/VoxPlane-MR-TestData" \
VOXPLANE_ENHANCED_CT_SAMPLE_DIR="$HOME/Documents/test_dicom/VoxPlane-EnhancedCT-TestData" \
PYTHONPATH=src QT_QPA_PLATFORM=cocoa uv run --group dev python -m pytest \
  tests/manual/test_display_mapping_samples.py tests/manual/test_mr_samples.py \
  tests/manual/test_enhanced_mr_samples.py tests/manual/test_enhanced_ct_samples.py -q
```

验收结果和原生截图见 [显示映射验证](validation/display-mapping-20260916/README.md)。
