# Scalar display shader

`scalar_display.frag.qsb` is checked in so installed apps do not require a shader compiler.
Rebuild after editing the GLSL source, using the qsb executable shipped with PySide6:

```sh
.venv/lib/python3.13/site-packages/PySide6/qsb --qt6 --qsbversion 64 \
  -o src/voxplane/qml/shaders/scalar_display.frag.qsb \
  src/voxplane/qml/shaders/scalar_display.frag
```

The Qt 6.4 serialization target is readable by the supported Qt 6.9+ runtime.
The package includes desktop/ES GLSL, HLSL and Metal variants. The image provider
encodes scalar values as 24-bit RGB with validity alpha; nearest texture access
and manual decoding **before** bilinear interpolation avoid byte-carry artifacts.
Window clipping/inversion and the color LUT run after scalar interpolation.
No display buffer replaces original measurement/QA pixels.

`tests/test_scalar_display.py` compares the rendered component with scalar-domain
reference pixels, including byte boundaries, padding, inversion and pseudocolor.
Normal offscreen tests cover the software path. To verify native Metal on macOS:

```sh
QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=metal \
  .venv/bin/python -m pytest tests/test_scalar_display.py -q
```

The Metal run asserts that the shader is actually active. Fusion compositing,
color images and supplemental overlays retain their dedicated display path.
