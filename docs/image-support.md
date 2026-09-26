# 支持的影像与格式

### 已支持的主要类型

| 影像类型 | 支持的 DICOM 输入 | 可用视图与功能 | 条件与限制 |
| --- | --- | --- | --- |
| **CT** | 常规单帧灰度 CT 序列 | 2D、多视口、平铺、2D / MPR 对比、MPR、3D；有效多时相组可用 4D，也可与 PET 融合 | MPR / 3D 要求规则空间采样；CT 4D 需要有效时相分组与跨相位几何检查。Enhanced CT 见下行 |
| **Enhanced CT** | Enhanced CT / Legacy Converted Enhanced CT；MONOCHROME2、有效共享／逐帧功能组；含有效显式补充调色板 | 分组后的 2D、平铺、对比；HU 规则体 MPR / 3D；补充彩色、单个线性 RWVM、逐帧导出 | 时相按组浏览，暂不接入 4D；非 HU／彩色派生图不开放 HU 分析和体重建；验证范围见 [Enhanced CT 测试数据](enhanced-ct-test-data.md) |
| **经典 MR** | 单帧 MR Image Storage；单采样 MONOCHROME1 / MONOCHROME2 | 2D、多视口、平铺、2D / MPR 对比；规则组支持 MPR、独立 3D、含 3D 的 MPR 四宫格 | 提供来源窗／自动窗、反白、测量与采集参数；不将 MR 强度解释为 CT HU |
| **Enhanced MR** | Enhanced MR Image Storage、Legacy Converted Enhanced MR；单采样灰度多帧，具有有效共享／逐帧功能组 | 按回波、b 值、扩散方向、时相及图像分量拆分浏览组；每组沿用 MR 阅片、对比、重建与导出功能 | 保留原文件与帧号。重建以单个规则组为单位，不把不同回波、时相或扩散方向拼成一个体；缺失维度不猜测 |
| **PET（模态 PT）** | 经典单帧 PET Image Storage；MONOCHROME2；SeriesType 为 STATIC / IMAGE 或 WHOLE BODY / IMAGE | 2D、2D / MPR 对比、独立 MPR / 3D、PET/CT 融合与融合 3D；按元数据提供源单位或 SUVbw | 不开放 PET 平铺、4D；动态／门控、Enhanced PET、多帧 PET 不在当前范围。缺少必要元数据时不提供 SUV 换算 |

**能显示二维切片，不代表一定能重建。** MPR / 3D 至少需要两层，且矩阵、像素间距、方向和参考坐标系一致，位置完整、无重复、间距规则。MR 还检查回波、扩散编码、时相与分量，定位像不进入重建；厚层影像的插值不会增加原始空间分辨率。

**MR 复用现有页签和工具。** 默认从中间层打开，窗值可保留三位小数；未明确来源单位时显示 **a.u.**。CT 组织窗模板、MTF／水模 QA、阈值分割、VOI 和去床板不会用于 MR。显示已有 ADC 图或将 fMRI 多帧分组浏览，不代表支持 ADC 计算、厂家定量换算或 fMRI 分析。

### 彩色 DICOM

RGB、YBR 与 PALETTE COLOR 支持二维、平铺、缩放、旋转、标注和 PNG 导出；可逐帧解码的普通多帧对象支持翻帧和播放。保留源颜色，不应用 CT 窗值、反白、伪彩或 HU / SUV 分析。物理尺寸测量需要有效 PixelSpacing；未标定图像不显示毫米标尺。彩色 MPR / 3D、视频编码、超声区域专用标定及大型病理图像不在此范围。

### 其他对象与尚未支持的格式

- **其他 DICOM 模态**：可读取对象可查看 Tag；部分可解码的单帧灰度图像可走通用 2D 路径。CR、DX、US、XA 等尚未完成专项验证，不将其列为完整支持的阅片或重建类型。
- **附属结果**：右侧「导入」支持与当前 MPR / 4D 原影像网格匹配的二值 SEG，含多个及重叠区域；CT、PET 和 MR 均可管理导入区域。支持 SEG 与 TID 1500 SR 导出，尚不支持 SR 导入、RTSTRUCT 交换或 Fractional / LABELMAP SEG。详见 [分割结果交换](mpr-segmentation-voi.md#seg-导入与管理)。
- **尚未开放的分析**：MR Mosaic、彩色 MR、波谱、MR 4D 播放、MR 融合、ADC／DTI／灌注／fMRI 分析。
- **非 DICOM 输入**：NIfTI（`.nii` / `.nii.gz`）、NRRD、厂家原始 MR 数据，以及普通 PNG／JPEG 图片不是当前影像导入格式。PNG 是导出格式。

### 归档格式与像素编码

文件按内容识别，不要求 `.dcm` 后缀。ZIP、RAR、7z、TAR 等是**文件／文件夹压缩包**，解压后读取其中的 DICOM；详细格式见 [压缩包导入](local-import.md)。

DICOM **像素压缩编码**与归档格式分开处理。本分支固定解码器依赖并随安装包收集：未压缩、RLE、JPEG Baseline / Extended（Process 1 / 2 & 4；仅 8 位）、JPEG Lossless（Process 14 / SV1）、JPEG-LS 无损／近无损、JPEG 2000 无损／有损。具体 UID、解码方式及安装包验证见 [压缩 DICOM](compressed-dicom.md)。

同一套解码策略用于阅片、重建、缩略图和 PNG 序列导出；不转存或修改源文件。缺少组件、未支持编码和像素解码失败分别提示。支持像素编码不扩大模态／SOP 对象范围：Enhanced CT、彩色对象和视频仍遵循上面的限制。有损数据解码不会恢复压缩前丢失的信息。

操作入口见软件内 **手册 → 快速开始 → 支持的影像与格式**；MR 细节见 [MR 基础阅片](mr.md)，公开样本及验证范围见 [MR 测试数据](mr-test-data.md) 和 [MR 界面复核](mr-ui-review-20260914.md)。

[返回 README](../README.md)
