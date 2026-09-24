<p align="center">
  <img src="src/qt_dicom_viewer/qml/assets/brand/voxenra-mark.svg" width="80" alt="Voxenra logo">
</p>

# Voxenra

[简体中文](README.md) | [English](README.en.md)

[产品主页](https://l5769389.github.io/voxenra/) · [在线操作手册](https://l5769389.github.io/voxenra/zh/)

面向 CT、MR 与 PET 的跨平台 DICOM 工作台，集阅片、三维重建、影像融合、测量分割与结果导出于一体。

[macOS · Apple Silicon](https://github.com/l5769389/voxenra/releases/download/v1.6.0/Voxenra-1.6.0-macos-arm64.dmg) · [Windows · 安装版](https://github.com/l5769389/voxenra/releases/download/v1.6.0/Voxenra-1.6.0-windows-x64-setup.exe) · [Windows · 便携版](https://github.com/l5769389/voxenra/releases/download/v1.6.0/Voxenra-1.6.0-windows-x64-portable.exe) · [版本记录](https://github.com/l5769389/voxenra/releases)

## 功能概览

| 模块 | 功能 |
| --- | --- |
| 影像管理 | 本地文件、文件夹与压缩包导入；PACS 查询下载；DICOM 标签查看。 |
| 二维阅片 | 调窗、伪彩、缩放、旋转、翻转、切片播放；平铺、多视口与多序列联动对比。 |
| 重建与三维 | 三平面 MPR、斜面重建、厚层投影；3D 体绘制、显示模板、裁剪；CT 多时相 4D。 |
| PET/CT 融合 | CT、PET、融合与 MIP 联动；手动刚性配准、融合比例调整、融合 3D。 |
| 测量与分割 | 长度、角度、曲线、矩形／椭圆／自由形状 ROI；阈值分割、VOI、区域管理与统计。 |
| 分析与报告 | CT 水模 QA、点源 MTF、斜坡线 FWHM 与层厚；PNG、DICOM、CSV / PDF、SEG / SR 导出。 |
| 工作区 | 多页签、独立窗口、灵活布局、保存恢复；深浅主题、语言包与离线手册。 |

## 二维阅片与序列对比

原始切片与标准切面重建清晰区分；支持 CT / MR 调窗、PET 定量范围、伪彩与切片播放。多视口可独立阅片，也可按位置或进度联动。

<table>
<tr>
<td width="50%"><b>MR 阅片</b><br><a href="docs/screenshots/07-mr-reading.png"><img src="docs/screenshots/07-mr-reading.png" alt="MR 原始切片与显示控制" width="100%"></a></td>
<td width="50%"><b>多序列 2D 对比</b><br><a href="docs/screenshots/08-enhanced-mr-compare.png"><img src="docs/screenshots/08-enhanced-mr-compare.png" alt="四组 MR 序列联动对比" width="100%"></a></td>
</tr>
<tr>
<td><b>自定义多视口</b><br><a href="docs/screenshots/10-2d-layout.png"><img src="docs/screenshots/10-2d-layout.png" alt="2D 网格布局" width="100%"></a></td>
<td><b>序列平铺与伪彩</b><br><a href="docs/screenshots/12-mr-montage.png"><img src="docs/screenshots/12-mr-montage.png" alt="切片平铺与色表选择" width="100%"></a></td>
</tr>
</table>

## MPR、3D 与 4D

- **MPR**：轴位、冠状位、矢状位联动，支持斜面重建、双序列对比及 MIP / MinIP / Mean / Sum 厚层投影。
- **3D**：CT、MR、PET 体绘制，支持模板、调窗、旋转和圈选裁剪；CT 提供 20 个模板。
- **4D**：CT 多时相同步播放，分割和 VOI 按时相保存。

**MPR 布局切换**：三平面与 3D 同屏，可调整布局、放大单个视图并记住布局。

![MPR 四宫格与布局切换](docs/screenshots/11-mpr-layouts.gif)

<table>
<tr>
<td width="50%"><b>斜面重建</b><br><a href="docs/screenshots/14-oblique-mpr.png"><img src="docs/screenshots/14-oblique-mpr.png" alt="旋转切面的斜面 MPR" width="100%"></a></td>
<td width="50%"><b>双序列 MPR 对比</b><br><a href="docs/screenshots/09-mpr-compare.png"><img src="docs/screenshots/09-mpr-compare.png" alt="两组影像的三平面联动对比" width="100%"></a></td>
</tr>
</table>

**3D 模板与旋转**

![CT 3D 模板切换与旋转](docs/screenshots/04-volume-presets.gif)

**4D 多时相播放**

![CT 多时相同步播放](docs/screenshots/03-4d-playback.gif)

## PET/CT 融合

CT、PET、融合切面与全体积 MIP 联动显示；可切换三向切面、调整色表与融合比例，进行手动刚性配准。融合 3D 可分别控制 CT 与 PET 的显示。

![PET/CT 切面与融合比例切换](docs/screenshots/05-pet-ct-fusion.gif)

<table>
<tr>
<td width="50%"><b>二维融合</b><br><a href="docs/screenshots/05-pet-ct-fusion.png"><img src="docs/screenshots/05-pet-ct-fusion.png" alt="CT、PET、融合和 MIP 四视图" width="100%"></a></td>
<td width="50%"><b>三维融合</b><br><a href="docs/screenshots/06-fusion-3d.png"><img src="docs/screenshots/06-fusion-3d.png" alt="CT 解剖结构与 PET 信号的三维融合" width="100%"></a></td>
</tr>
</table>

## 测量、分割与报告

- **测量**：长度、角度、曲线、矩形／椭圆／自由形状 ROI，提供面积、周长和强度统计；支持编辑、复制粘贴、撤销重做。
- **分割**：MPR 阈值分割、自由形状 ROI 转单层分割、VOI 分析；多个区域可独立命名、着色、显隐与统计。
- **结果**：测量导出 CSV / PDF 或 DICOM SR；分割导出 DICOM SEG，并可导入匹配当前影像的 SEG。

**自由形状测量**：逐点点击添加控制点，生成平滑闭合轮廓并统计。

![自由形状 ROI 绘制与统计](docs/screenshots/01-freehand-measurement.gif)

**曲线测量**：少量控制点确定平滑路径，测量实际弧长。

![曲线测量与控制点](docs/screenshots/33-curve-measurement.gif)

**分割结果交换**

![ROI 转分割、导出与重新导入 SEG](docs/screenshots/02-segmentation-exchange.gif)

<table>
<tr>
<td width="50%"><b>关联结果导入</b><br><a href="docs/screenshots/33-associated-import.png"><img src="docs/screenshots/33-associated-import.png" alt="右侧导入匹配影像的 SEG" width="100%"></a></td>
<td width="50%"><b>结构化测量报告</b><br><a href="docs/screenshots/32-structured-report.png"><img src="docs/screenshots/32-structured-report.png" alt="SEG 与 SR 结果导出" width="100%"></a></td>
</tr>
<tr>
<td><b>CT 水模 QA</b><br><a href="docs/screenshots/19-water-qa.png"><img src="docs/screenshots/19-water-qa.png" alt="CT 值、噪声与均匀性分析" width="100%"></a></td>
<td><b>点源 MTF</b><br><a href="docs/screenshots/28-mtf-analysis.png"><img src="docs/screenshots/28-mtf-analysis.png" alt="独立的点源 MTF 曲线与空间分辨率分析" width="100%"></a></td>
</tr>
</table>

## 数据管理与工作区

左侧导入原始影像，右侧导入关联 SEG。支持文件／文件夹／压缩包混选和拖入、PACS 查询下载、DICOM 标签查看，以及 PNG 和源 DICOM 导出。

多页签可拖出成为独立窗口；工作区保存影像引用、布局与操作状态，并提供自动恢复。支持深浅主题、中英葡内置语言与本地 JSON 语言包、可收起侧栏及可搜索的离线手册。

<table>
<tr>
<td width="50%"><b>本地导入</b><br><a href="docs/screenshots/15-mixed-import.png"><img src="docs/screenshots/15-mixed-import.png" alt="文件、文件夹与压缩包混合导入" width="100%"></a></td>
<td width="50%"><b>PACS 浏览器</b><br><a href="docs/screenshots/16-pacs-browser.png"><img src="docs/screenshots/16-pacs-browser.png" alt="PACS 检查查询与序列下载" width="100%"></a></td>
</tr>
<tr>
<td><b>独立窗口</b><br><a href="docs/screenshots/13-detached-tabs.png"><img src="docs/screenshots/13-detached-tabs.png" alt="页签分离为独立窗口" width="100%"></a></td>
<td><b>浅色主题</b><br><a href="docs/screenshots/26-theme-light.png"><img src="docs/screenshots/26-theme-light.png" alt="浅色主题下的 MPR 工作台" width="100%"></a></td>
</tr>
</table>

[查看完整界面图集](docs/screenshots/README.md)

## 支持范围

- 支持常规 CT / MR / PET、Enhanced CT / MR，以及 RLE、JPEG、JPEG-LS、JPEG 2000 像素解码。MPR / 3D 需要规则空间采样，PET 定量取决于影像元数据。
- 暂不支持 NIfTI / NRRD、动态／门控 PET、MR 4D、fMRI / DTI 分析，以及 SR / RTSTRUCT 导入。
- SEG / SR 保留源身份与影像引用，不使用 PNG / 普通 DICOM 导出的匿名选项。

## 文档与运行

[在线操作手册](https://l5769389.github.io/voxenra/zh/) · [影像支持](docs/image-support.md) · [本地导入](docs/local-import.md) · [PACS](docs/pacs.md) · [PET 与融合](docs/pet-mpr-fusion.md) · [分割与 VOI](docs/mpr-segmentation-voi.md) · [导出](docs/export.md) · [离线手册说明](docs/manual.md) · [开发与打包](docs/packaging.md)

```bash
uv run voxenra
```
