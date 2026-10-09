<p align="center">
  <img src="src/qt_dicom_viewer/qml/assets/brand/voxenra-mark.svg" width="80" alt="Voxenra logo">
</p>

# Voxenra

[简体中文](README.md) | [English](README.en.md)

[产品主页](https://l5769389.github.io/voxenra/) · [在线操作手册](https://l5769389.github.io/voxenra/zh/)

面向 CT、MR 与 PET 的跨平台 DICOM 工作台，集阅片、三维重建、影像融合、测量分割与结果导出于一体。

[macOS · Apple Silicon](https://github.com/l5769389/voxenra/releases/download/v2.0.2/Voxenra-2.0.2-macos-arm64.dmg) · [Windows · 安装版](https://github.com/l5769389/voxenra/releases/download/v2.0.2/Voxenra-2.0.2-windows-x64-setup.exe) · [Windows · 便携版](https://github.com/l5769389/voxenra/releases/download/v2.0.2/Voxenra-2.0.2-windows-x64-portable.exe) · [版本记录](https://github.com/l5769389/voxenra/releases)

## 功能概览

| 模块 | 功能 |
| --- | --- |
| 影像管理 | 本地文件、文件夹与压缩包导入；PACS 查询下载；DICOM 标签查看。 |
| 二维阅片 | 调窗、伪彩、缩放、旋转、翻转、切片播放；平铺、多视口与多序列联动对比。 |
| 重建与三维 | 三平面 MPR、斜面重建、厚层投影；3D 体绘制、显示模板、裁剪；CT 多时相 4D。 |
| PET/CT 融合 | CT、PET、融合与 MIP 联动；手动刚性配准、融合比例调整、融合 3D。 |
| 测量与分割 | 长度、角度、曲线、矩形／椭圆／自由形状 ROI；阈值分割、画笔／橡皮精修、VOI 与区域统计。 |
| 分析与报告 | CT 水模 QA、点源 MTF、斜坡线 FWHM 与层厚；PNG、DICOM、CSV / PDF、SEG / SR 与 NRRD 导出。 |
| 工作区 | 多页签、独立窗口、灵活布局、保存恢复；深色／中性深灰／浅色主题、语言包与离线手册。 |

## 二维阅片与序列对比

原始切片与标准切面重建清晰区分；支持 CT / MR 调窗、PET 定量范围、伪彩与切片播放。多视口可独立阅片，也可按位置或进度联动。

<table>
<tr>
<td width="50%"><b>MR 阅片</b><br><a href="docs/screenshots/07-mr-reading.png"><img src="docs/screenshots/07-mr-reading.png" alt="MR 阅片" width="100%"></a></td>
<td width="50%"><b>自定义多视口</b><br><a href="docs/screenshots/10-2d-layout.png"><img src="docs/screenshots/10-2d-layout.png" alt="自定义多视口" width="100%"></a></td>
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

- **测量**：长度、角度、曲线、矩形／椭圆／自由形状 ROI，提供面积、周长和强度统计；支持列表定位、重命名、显隐、锁定、复制粘贴与撤销重做。
- **分割**：MPR 阈值分割、画笔／橡皮精修、连通区域保留或删除、自由形状 ROI 转单层分割；支持轮廓／填充与不透明度调节、独立区域管理、VOI 分析和撤销重做。
- **结果**：测量导出 CSV / PDF 或 DICOM SR，PDF 自动匹配测量所在平面的参考图；分割支持 DICOM SEG 和 NRRD / Slicer 往返交换，保留重叠区域、名称与颜色。

**自由形状测量**：逐点点击添加控制点，生成平滑闭合轮廓并统计。

![自由形状 ROI 绘制与统计](docs/screenshots/01-freehand-measurement.gif)

**曲线测量**：少量控制点确定平滑路径，测量实际弧长。

![曲线测量与控制点](docs/screenshots/33-curve-measurement.gif)

**分割精修**：毫米或相对视图尺寸的画笔与橡皮，支持当前切面或 3D 球形范围。

![MR 分割绘制、擦除与撤销重做](docs/screenshots/38-segmentation-refinement.gif)

<table>
<tr>
<td width="50%"><b>关联结果导入</b><br><a href="docs/screenshots/33-associated-import.png"><img src="docs/screenshots/33-associated-import.png" alt="右侧导入匹配影像的 SEG / NRRD" width="100%"></a></td>
<td width="50%"><b>分割与报告导出</b><br><a href="docs/screenshots/32-structured-report.png"><img src="docs/screenshots/32-structured-report.png" alt="SEG、SR 与 NRRD 导出" width="100%"></a></td>
</tr>
<tr>
<td><b>CT 水模 QA</b><br><a href="docs/screenshots/19-water-qa.png"><img src="docs/screenshots/19-water-qa.png" alt="CT 值、噪声与均匀性分析" width="100%"></a></td>
<td><b>点源 MTF</b><br><a href="docs/screenshots/28-mtf-analysis.png"><img src="docs/screenshots/28-mtf-analysis.png" alt="独立的点源 MTF 曲线与空间分辨率分析" width="100%"></a></td>
</tr>
</table>

## 数据管理与工作区

左侧导入原始影像，右侧导入关联 SEG / NRRD 分割。支持文件／文件夹／压缩包混选和拖入、PACS 查询下载、DICOM 标签查看，以及 PNG 和源 DICOM 导出。

多页签可拖出成为独立窗口；工作区保存影像引用、布局、测量、分割掩膜与分析结果，并恢复之前选择的工具和精修参数。支持自动恢复、深色／中性深灰／浅色主题、本地 JSON 语言包与窗模板、离线手册、反馈和可关闭的启动更新检查。

<table>
<tr>
<td width="50%"><b>本地导入</b><br><a href="docs/screenshots/15-mixed-import.png"><img src="docs/screenshots/15-mixed-import.png" alt="文件、文件夹与压缩包混合导入" width="100%"></a></td>
<td width="50%"><b>PACS 浏览器</b><br><a href="docs/screenshots/16-pacs-browser.png"><img src="docs/screenshots/16-pacs-browser.png" alt="PACS 检查查询与序列下载" width="100%"></a></td>
</tr>
<tr>
<td><b>独立窗口</b><br><a href="docs/screenshots/13-detached-tabs.png"><img src="docs/screenshots/13-detached-tabs.png" alt="页签分离为独立窗口" width="100%"></a></td>
<td><b>工作区恢复</b><br><a href="docs/screenshots/36-workspace-full.png"><img src="docs/screenshots/36-workspace-full.png" alt="MR 阅片与工作区操作" width="100%"></a></td>
</tr>
</table>

## 外观与操作偏好

在 **设置 → 外观与语言** 中选择 **深色、中性深灰或浅色**。中性深灰采用石墨灰面板与低饱和青色强调，保持影像区域突出。主题即时生效并在重启后保留，影像窗宽窗位与色表独立设置。

![中性深灰主题下的 MR 阅片](docs/screenshots/37-theme-graphite.png)

[深色主题](docs/screenshots/25-theme-dark.png) · [浅色主题](docs/screenshots/26-theme-light.png)

可设置界面大小、鼠标拖动、滚轮方向与工具快捷键，重复或保留按键会被拦截。隐私设置支持新视图隐藏身份叠加、清除最近工作区记录。

![鼠标操作与工具快捷键设置](docs/screenshots/40-input-settings.png)

更新提示按界面语言显示简短摘要，可查看完整发布说明。[更新弹窗](docs/screenshots/43-update-summary.png)

[查看完整界面图集](docs/screenshots/README.md)

## 支持范围

- 支持常规 CT / MR / PET、Enhanced CT / MR，以及 RLE、JPEG、JPEG-LS、JPEG 2000 像素解码。MPR / 3D 需要规则空间采样，PET 定量取决于影像元数据。
- 常见 RGB、YBR 与 PALETTE COLOR DICOM 支持二维、平铺、多帧播放及 PNG 导出；物理尺寸测量需要有效像素间距，不开放彩色 MPR / 3D 或 HU 分析。
- NRRD 支持当前时相体数据导出，以及匹配原始网格的分割导入导出；暂不提供独立 NRRD 影像浏览或自动重采样。
- 暂不支持 NIfTI、动态／门控 PET、MR 4D、fMRI / DTI 分析，以及 SR / RTSTRUCT 导入。
- SEG / SR 保留源身份与影像引用，不使用 PNG / 普通 DICOM 导出的匿名选项。

## 文档与运行

[在线操作手册](https://l5769389.github.io/voxenra/zh/) · [影像支持](docs/image-support.md) · [本地导入](docs/local-import.md) · [PACS](docs/pacs.md) · [PET 与融合](docs/pet-mpr-fusion.md) · [分割与 VOI](docs/mpr-segmentation-voi.md) · [导出](docs/export.md) · [离线手册说明](docs/manual.md) · [开发与打包](docs/packaging.md)

```bash
uv run voxenra
```
