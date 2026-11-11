# Enhanced CT 多帧：测试数据与验收

首轮实现基于 `main` 的 `8baa018`，分支 `codex/enhanced-ct`，worktree 为 `/Users/jun/Documents/git-repo/qt-dicom-viewer/.worktrees/enhanced-ct`。下载与验证日期：2026-09-16。

原始影像位于文稿目录 `/Users/jun/Documents/test_dicom/Voxenra-EnhancedCT-TestData`。共 **2 个原始 DICOM、56 帧**，没有转换为经典 CT，也没有修改原始标签或像素。样本不纳入 Git；来源、大小、SHA-256 见该目录的 `manifest.json` 和 `SHA256SUMS.txt`。

| 本地文件 | 来源与内容 | 验收预期 |
| --- | --- | --- |
| `NEMA-2006/01-CT0001` | NEMA Enhanced CT 演示包中的 `DISCIMG/IMAGES/CT0001`；54 帧、512×512、未压缩、心脏 CT、HU | 一个 54 层浏览组；逐帧位置排序，2D、平铺、对比、MPR 与 3D |
| `pydicom/eCT_Supplemental.dcm` | pydicom-data 中的 NEMA `CT0012`；2 帧、512×512、灌注 RCBF 派生图、补充调色板、RescaleType=US | 2 帧彩色浏览、平铺与 PNG 导出；按单个线性 RWVM 显示 `ml/100ml/s`；禁用 HU 分析和体重建 |

正向样本的面内间距为 0.597656 mm，层间距及层厚均为 3 mm。文件中的厂商为演示名称 `Acme Medical Devices`，不能据此宣称某个真实厂商或所有扫描协议已经验收。54 帧已覆盖完整文件；厚层重建的条纹和有限上下覆盖范围来自原始采样。

## 本轮行为

- 支持 Enhanced CT Image Storage (`1.2.840.10008.5.1.4.1.1.2.1`) 与 Legacy Converted Enhanced CT (`1.2.840.10008.5.1.4.1.1.2.2`) 的 HU 灰度帧。
- 从共享／逐帧功能组提取位置、方向、间距、Rescale、窗位窗宽、CT 帧类型、重建核、kVp 和小数 mA。按帧解码，不把整个多帧像素数组交给单张图渲染。
- 按 Stack、时相、重建属性和声明的非空间维度拆分稳定浏览组；保留原始 Series/SOP UID、文件与帧号。未知非空间维度不拼为空间层。
- 单个规则组可构建 MPR / 3D；重复位置、缺失／非法几何、混合组不进入体重建。格式异常对象仍保留 Tag 入口。
- 非 HU 标量帧支持 2D 浏览；有效的 8/16 位显式 RGB 补充调色板按存储值应用：低于首个映射值走灰度窗，其余值查表并在末端截断。原始模式下调窗与反白不改变源颜色；[显示映射](display-mapping.md) 另提供带单位的自定义彩色范围。
- 单个有效线性 Real World Value Mapping 为光标／ROI 提供单位和数值，独立于灰度窗口的 Rescale 域；未支持的多映射／非线性映射保留来源缩放单位（US 显示 a.u.），不假设 HU。
- 侧栏明确显示浏览组帧数和源文件数，例如 `54 帧 · 1 文件`、`2 帧 · 1 文件`。
- PNG 导出只包含所选组的帧；DICOM 导出保留完整原对象，可能含其他时相／组。匿名导出在副本上操作。

Enhanced CT 的时相当前分组浏览，**尚未接入 4D 播放**。尚未实现灌注参数计算、多能量材料分析、非线性／多个 RWVM 映射选择或分段调色板。非 HU／补充彩色图可显示与测量，但不开放 HU 预设、QA／MTF 或体重建。真实样本覆盖未压缩普通 HU 和彩色 RCBF 浏览两条路径；Legacy Converted、RLE、逐帧变化缩放、异常几何与多对象合并由合成回归覆盖，JPEG/JPEG-LS/JPEG 2000 使用合并后的固定内置解码组件，具体限制见 [压缩 DICOM](compressed-dicom.md)。

## 补充彩色验证

RCBF 样本共有 2 帧，RGB 三通道各 100 项、首个映射存储值为 1024、16 位精度。每帧存储值低于 1024 的像素使用灰度窗口；其余查表，超过 1123 的值取最后一项。源 RWVM 声明 `value = stored − 1024`、有效范围 0–4095，单位 `ml/100ml/s`。这是读取现有派生结果，不是从动态 CT 计算血流。

实现依据 [DICOM Pixel Presentation](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.16.2.html) 与 [Supplemental Palette Color LUT Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.19.html)。

## 来源与复现

- [PixelMed / NEMA 公开多帧测试项目](https://www.pixelmed.com/nemamf.html)说明 CT 测试影像公开发布。原包：`ftp://medical.nema.org/medical/dicom/Multiframe/CT/nemamfct.images.tar.bz2`（2006-12-20，572,054,357 字节）。本地仅流式提取 CT0001，未保存完整大包。
- [pydicom-data 固定版本](https://github.com/pydicom/pydicom-data/tree/abc42b90985fb6cf385aa4af766d2c9c94a257a4)提供灌注样本；[pydicom 来源说明](https://github.com/pydicom/pydicom/blob/d80e8b1791f7a3dfd753f36400abc9f9941423f2/src/pydicom/data/test_files/README.txt)确认原文件为同一 NEMA 包的 CT0012。上游项目 LICENSE 随数据保留；不将代码仓库的许可证扩张解释为所有影像的独立授权。
- 实现参考 [DICOM CT 像素变换宏](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.15.3.10.html)和[多帧功能组](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.16.html)。显示值逐帧使用 `stored × slope + intercept`，不以顶层经典属性替代缺失的 Enhanced CT 几何或缩放。

从本 worktree 启动 `uv run voxplane`，打开 `NEMA-2006` 文件夹即可验证。原文件没有 `.dcm` 后缀，应用按内容识别。导入根目录还会出现 2 帧灌注图；已有导入需重新扫描以更新浏览组。

复跑公开样本验收（需要本地样本和开发依赖；原生 3D 使用 `cocoa`）：

```sh
VOXPLANE_ENHANCED_CT_SAMPLE_DIR="$HOME/Documents/test_dicom/Voxenra-EnhancedCT-TestData" \
  PYTHONPATH=src:tests:tests/manual QT_QPA_PLATFORM=cocoa \
  uv run --group dev python -m pytest tests/manual/test_enhanced_ct_samples.py -q
```

无显示环境可使用 `QT_QPA_PLATFORM=offscreen`，此时跳过原生窗口测试。没有配置样本路径时外部数据测试跳过。验收截图与运行结果见 [本轮验证记录](validation/enhanced-ct-20260916/README.md)。
