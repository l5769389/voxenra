# 压缩 DICOM 像素

ZIP/RAR 等归档解包与 Pixel Data 解码互不替代。应用固定以下运行依赖，并将原生库与插件元数据随包收集；不需要用户安装外部解码程序。

| 传输语法 UID 后缀（前缀 1.2.840.10008.1.2） | 格式 | 固定解码路径 |
| --- | --- | --- |
| .5 | RLE Lossless | pydicom 3.0.2 |
| .4.50 / .4.51 | JPEG Baseline / Extended（仅 8 位） | python-gdcm 3.2.1 |
| .4.57 / .4.70 | JPEG Lossless / SV1 | python-gdcm 3.2.1 |
| .4.80 / .4.81 | JPEG-LS 无损 / 近无损 | pyjpegls 1.5.1 |
| .4.90 / .4.91 | JPEG 2000 无损 / 有损 | pylibjpeg 2.1.0 + pylibjpeg-openjpeg 2.5.0 |

未压缩继续由 pydicom 读取。JPEG Extended 的 12 位精度当前不支持；入口明确提示此限制，不将其误报为文件损坏。HTJ2K、JPEG XL、JPEG XT、MPEG/H.264/H.265 等不在此次承诺范围；不通过本机偶然安装的其他插件静默扩展支持。编码参数仍需符合解码器及影像对象限制。使用有损语法不表示恢复了压缩前的像素。

## 数据与错误

阅片、重建、缩略图、PNG 序列导出共用 `pixel_codecs` 策略。先检查传输语法和指定插件，再解码像素，沿用 Modality LUT / Rescale、MR 逐帧缩放与 padding 处理。原始文件、UID、几何与压缩标记不被改写。

错误区分：未支持编码／精度、安装包缺少解码组件、像素解码失败。对于不超过 64 MiB 且存在混合 VR 的旧文件，流式解析失败时允许通过完整 DICOM 解析恢复 Pixel Data，仍使用同一个指定解码器；逐帧导出已输出帧后不回退，避免重复输出。最后一种可能是损坏或不支持的编码参数，不能据此断言文件一定损坏。中英文提示不暴露患者内容或源路径。PNG 序列导出失败会清理本次临时输出；源 DICOM 复制无需解码器，匿名规则不变。

支持压缩不扩大影像对象范围：当前 CT/MR/PET 范围见 [影像支持](image-support.md)。Enhanced MR 仍按原文件和帧号逐帧解码，禁止先将整个对象转为临时单帧文件。

## 打包验证

`hook-voxplane.core.pixel_codecs.py` 收集解码插件、原生扩展和发行包元数据。macOS、Windows 安装版以及便携版构建工作流均调用实际可执行文件的 `--verify-pixel-codecs` 模式；无需启动界面，无需读取用户影像。

```sh
uv run --locked --group build python scripts/verify_pixel_codecs.py \
  --executable dist/macos/VoxPlane.app/Contents/MacOS/VoxPlane
# Windows 安装版路径：dist/windows/VoxPlane/VoxPlane.exe
# Windows 便携版路径：dist/VoxPlane.exe
```

脚本生成带已知像素值的 RLE、JPEG-LS、JPEG 2000、JPEG Baseline 合成对象，再由冻结程序独立解码、核对形状和像素摘要。同时检查表中全部指定插件可用。结果位于 `build/codec-check/result.json`；失败会阻止工作流继续上传／发布。本地某一平台验证不代表另一平台已完成验收。

源码回归另覆盖 CT/MR 符号位、负值与 rescale，MPR 体数据、Enhanced MR 逐帧缩放、PNG 导出、缩略图和错误清理；使用 pydicom 自带 JPEG Lossless RGB 样本检查解码，不由此宣称彩色主阅片支持。

参考：[pydicom 解码组件](https://pydicom.github.io/pydicom/stable/guides/user/image_data_handlers.html)。第三方声明随原生依赖元数据及安装包许可证目录保留。
