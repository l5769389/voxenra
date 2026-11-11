# MR 测试数据与验收

数据位于 `/Users/jun/Documents/Voxenra-MR-TestData`，供独立 worktree `/Users/jun/Documents/git-repo/qt-dicom-viewer-mr`（`codex/mr-support`）测试。请从该源码启动；此前的发布安装包不包含本次功能。下载与验证日期：2026-09-14。原始 DICOM 未转换、未修改像素或标签。

## 数据清单与预期

| 目录 / 文件 | 原始内容 | 当前预期 |
| --- | --- | --- |
| `01_T1_Brain_HFS` | Siemens 经典 T1，35 层，仰卧 | 2D、平铺、MPR、3D；层间距约 4.8 mm，重建较粗 |
| `02_T1_Brain_HFDR` | Siemens 经典 T1，35 层，右侧卧 | 同上；用于核验体位与方向，不能与 HFS 自动配准 |
| `Enhanced-MR/In/Philips/IM_0006_T1.dcm` | 64 帧 T1 | 幅度与相位分为 2 组，每组 32 层 |
| `Enhanced-MR/In/Philips/IM_0027_fMAP.dcm` | 64 帧 B0 | 幅度和 REAL 场图分为 2 组，每组 32 层；不执行定量换算 |
| `Enhanced-MR/In/Philips/IM_0035_fMRI.dcm` | 256 帧，2 个回波 × 4 个时相 | 8 组，每组 32 层，可选 2–4 组对照；没有 fMRI 分析或 4D 播放 |
| `Enhanced-MR/In/Canon/DTI_PA.dcm` | 520 帧扩散，b=0 与 12 个 b=1500 方向 | 13 组，每组 40 层；不把方向叠成空间层，不计算 DTI |
| `Enhanced-MR/In/Siemens/XA10` | 4 个对象，各 6 帧 | 4 个时相组，各 6 层 |
| `Thin-3D-T1/DICOM` | Siemens MPRAGE，192 个经典单帧，1 mm 各向同性 | 用于 MR 3D、三平面 MPR 与含 3D 的四宫格 |
| `90_Unsupported_Mosaic` | Siemens 扩散 Mosaic，13 个文件 | 只开放 Tag；不能把拼图当作一个解剖切面 |
| `91_Unsupported_EnhancedMR` | 历史测试文件，与上面的 Philips T1 内容相同 | **现在已支持**，应分成 2 组。保留旧目录名与原文件，避免破坏既有路径和校验记录 |

新增 Enhanced 目录共有 **8 个 DICOM、928 帧、29 个浏览组**。组内可用 MPR / 3D；图像质量受原始层厚、间距和信号影响。应用按源文件计导入数量，按分组内帧数计切片数量。不要把旧 `91_` 与新增 Philips T1 重复计算成两套数据。

两套厚层 T1 的矩阵为 256 × 256，TR 300 ms、TE 2.46 ms、层厚 4 mm、面内间距 1.015625 mm，切片位置间距约 4.8 mm。重建采用位置间距，插值不会补回层间缺失的信息。两套源文件 PatientName 都是 `HFS`，体位应查看 Tag 中的 PatientPosition；检查时间分别为 15:01:38 与 15:11:57。

本轮再次进行实际桌面操作，修复中间层滑块、辅助功能按钮和工作区活动序列等问题；最新结果为 **1437 项全量通过，另有 18 项原生验收通过**。详见 [2026-09-14 界面复核记录](mr-ui-review-20260914.md)，证据在 `ui-review-20260914/`。

## 建议操作顺序

1. 在 MR worktree 按项目 README 启动应用，打开 `Thin-3D-T1/DICOM`。2D 应默认显示中间层，测试滚轮、平移、缩放、旋转、镜像、长度和 ROI。MR 未明确强度单位时显示 a.u.，不使用 HU。
2. 在调窗面板测试三位小数输入、自动窗、反白、重置。翻页保留当前窗值；CT 窗模板、去床板、水模 QA、MTF、阈值分割与 VOI 不用于 MR。
3. 打开 MPR，检查三方向、定位线、斜位、厚层投影和七种布局。四宫格应包含 MR 3D 参考。独立 3D 可选择 MR 灰度体绘制、MR 高信号和 MR MIP，测试方向、缩放、浮点调窗、自动窗、裁剪和 PNG。体绘制是强度展示，不是组织分割模型。
4. 单独导入 `Enhanced-MR/In/Philips/IM_0035_fMRI.dcm`，列表应出现 8 组、每组 32 层。查看 TE 与 t 标签，选择 2–4 组打开 Compare 2D；调窗和反白默认独立。
5. 对照默认使用患者坐标模式。平行序列按空间位置匹配；只有相同检查、相同非空 Frame of Reference 且患者 ID 一致时才联动。其他视口可显示活动平面定位线，Alt＋单击图像进行跨方向定位。不同患者空间或超出覆盖范围时不强制跳层；需要按比例浏览时手动选相对进度。
6. 导入其余 Enhanced 数据，核对上表分组数量。翻页、平铺、缩略图、Tag 应对应正确源帧。Canon 的不同扩散方向、Philips 的幅度与相位不能混成一个体。
7. 保存 / 恢复四窗工作区，检查各视口层号、独立窗值和联动模式。旧版经典 MR 工作区仍可根据源 UID 恢复。
8. 选择一个 Enhanced 组导出：**PNG 只含当前组**；**DICOM 保留完整原始多帧对象，可能包含其他组**。匿名导出到新目录后重导入，像素与逐帧几何应保持一致。Tag 显示完整源对象。
9. 导入 Mosaic 验证明确的格式提示与 Tag 入口。旧 `91_Unsupported_EnhancedMR` 已转为正向测试，不应继续提示“仅支持经典单帧 MR”。

## 来源、许可与校验

| 上游项目 | 固定版本 | 本地内容 |
| --- | --- | --- |
| [dcm_qa_decubitus](https://github.com/neurolabusc/dcm_qa_decubitus) | `92cd635dc0a8f971d0e1d4e4ce69efff70fdc04e` | 厚层 T1 与 Mosaic |
| [dcm_qa_enh](https://github.com/neurolabusc/dcm_qa_enh) | `58953e7b0150c6b866b2cc2fc2b40366625672dc` | 8 个 Enhanced DICOM 与原项目 NIfTI / JSON / bval / bvec 参考 |
| [dcm_qa_mprage](https://github.com/neurolabusc/dcm_qa_mprage) | `733b489fdea90371452014f4c1bbc19a9f5af463` | `6_T1_mprage_ns_sag_p2.zip`、完整 192 层解压文件及对应参考 |

三个上游均提供 BSD-2-Clause 许可，来源 README 与 LICENSE 随数据保留。Philips 数据的来源致谢保留在原项目 README 中。`manifest.json` 记录固定来源、大小与 SHA-256；新增两组各有独立 manifest，薄层组另记录解压文件校验值。根目录的 `SHA256SUMS.txt` 仅覆盖首轮样本，不能据此声称已校验新增全部文件。

## 验证方法与结果文件

- 全部 928 个 Enhanced 帧逐像素对照原始 PixelData 与标准逐帧 Rescale；每帧抽取 4 个位置，与上游 NIfTI 的存储像素和患者坐标独立比较。29 组均检查体数据与缩略图。
- 薄层 T1 检查 192 层体积、1 mm 三轴间距，并在多个层面抽样对照 NIfTI 像素和空间坐标。原生 VTK 验证三种 MR 预设与 MPR 共享体数据。
- 真实 QML 验证 2–4 组选择与布局、空间翻页、调窗、测量、MPR、工作区、导出。跨方向 Alt 定位、旋转 / 镜像后的映射，以及缺少公共患者空间的保护另有合成几何回归。
- Philips 上游 NIfTI 采用私有 precise scaling。本次参考比较使用**未缩放存储值**，软件显示值另按标准 Rescale 验证；未实现 Real World Value Mapping 或厂家私有定量换算，不能据此推导 ADC、场强或跨序列强度一致。
- 实际显示检查发现并修复了边缘切片窄窗导致的初始过曝：MR 2D 从中间层开始，MPR 初始窗取完整体数据范围；MR MIP 自动窗覆盖完整有限范围，避免沿用普通分位窗造成投影截白。此前修复的 Retina PNG 尺寸和共享面板释放问题也保留回归覆盖。

上一轮验收结果：**1429 项自动回归通过、31 项跳过；最后 MR 背景掩膜修正后 113 项相关回归通过；18 项原生验收通过（15 项公开样本 + 3 项合成 UI/VTK）**。本轮报告、校验摘要与截图保存在 `acceptance-enhanced/`，汇总见 `validation-enhanced.json`。原 `validation.json`、`acceptance/` 为首轮历史记录，其中“Enhanced 不支持”是旧状态，以本指南为准。QML 窗口截图不包含原生 VTK 子窗口时，单独的 `mr-general.png` / `mr-mpr-reference.png` 用于核验实际 3D 输出，不以空白子区作为 3D 结果。

这批真实数据覆盖 Siemens、Philips、Canon 的所列格式，不代表 GE、所有扫描协议、压缩传输语法或定量分析已经验证。Legacy Converted Enhanced MR、MONOCHROME1、小数缩放、RLE 与异常功能组另由合成回归覆盖。应用仍不导入 NIfTI，参考文件仅供测试。

在 MR worktree 中复跑（需开发依赖与本地样本）：

```sh
VOXPLANE_MR_SAMPLE_DIR="$HOME/Documents/Voxenra-MR-TestData" \
  PYTHONPATH=src:tests:tests/manual QT_QPA_PLATFORM=cocoa \
  uv run --group dev python -m pytest \
  tests/manual/test_mr_samples.py tests/manual/test_enhanced_mr_samples.py -q
```

macOS 原生验证使用 `cocoa` 与默认硬件渲染，不设置 QT_QUICK_BACKEND；无显示环境可改为 `offscreen`，原生 3D 案例会跳过。未配置 VOXPLANE_MR_SAMPLE_DIR 时外部样本测试跳过。
