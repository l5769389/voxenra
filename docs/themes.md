# 主题与样式维护

## 数据入口

`src/qt_dicom_viewer/qml/theme/palettes.json` 是配色的唯一手工维护入口：

- `defaults`：按用途命名的界面颜色，也是缺失颜色的回退值。
- `themes`：内置主题的差异值；目前包含 `dark`（原深色）、`graphite`（中性深灰）和 `light`。
- `imaging`：影像画布、测量、标注、方向标记等固定颜色，不随界面主题变化。
- `metrics`：已有公共组件使用的字号、图标尺寸、圆角和控件高度。
- `swatches`：用户可选的标注、分割和叠加文字色板。这些是数据颜色，不是界面选中状态。

Python 的 `ui/theme_palette.py` 合并默认值和主题差异，供外观控制器和 QWidget
对话框使用。QML 组件统一通过 `theme/Theme.qml` 引用语义角色，例如
`Theme.panelBackground`、`Theme.textMuted`、`Theme.controlHover`。
`AppearanceController` 负责响应设置和更新 Qt 原生调色板，不再维护颜色表。

`PaletteData.js` 是自动生成的 QML 数据副本，用于没有 Python 控制器的独立组件预览、
主题缩略图和固定影像颜色。不要手工编辑它。修改 JSON 后执行：

```sh
.venv/bin/python scripts/generate_theme_data.py
.venv/bin/python scripts/generate_theme_data.py --check
```

两个数据文件均纳入 QRC 和冻结应用资源，测试检查生成文件是否与源文件一致。

## 中性深灰

设置 → 外观与语言 → 中性深灰。面板、卡片、控件和选中背景使用中性灰阶，
低饱和青色用于强调图标、焦点、活动视口边框和主要操作。活动视口采用 2 px 边框，
切换选中状态不改变影像区域尺寸；序列数量使用次要文字色。面板外框与页签边框
分别通过 `panelBorder`、`tabSelectedBorder` 控制，不削弱输入框边界。保留原深浅主题与默认值，选择会随设置保存。
主题按钮在较窄的内容区自动换行；影像画布、测量、分割及方向标记颜色不变。

## 修改与扩展规则

1. 组件使用颜色角色，不写十六进制颜色；`transparent` 仍可直接使用。
2. 新增用途先在 `defaults` 定义角色，再为其他主题提供需要的差异值；未知字段由加载器拒绝。
3. 新增主题还需要注册设置允许值、主题选择入口及名称翻译；本次没有增加用户语言包式的主题导入功能。
4. 界面主题不能覆盖 `imaging`，也不能修改影像的窗宽窗位、色表、分割数据或用户自定义标注颜色。
5. Canvas 绘制的界面插图必须在主题切换时请求重绘。手册示意图使用 `diagram*`，影像上叠加的几何线使用固定影像角色。
6. 主题缩略图读取实际主题数据，避免手写一套与实际界面不一致的配色。

## 验证

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  .venv/bin/python tests/run_isolated.py \
  tests/test_theme_palette.py tests/test_theme_ui.py \
  tests/test_appearance_language.py tests/test_manual.py \
  tests/test_dialog_layout_qml.py tests/test_workspace_dialog_layout.py \
  --output build/theme-refactor/tests
```

在可显示桌面的环境中，去掉 `QT_QPA_PLATFORM=offscreen` 可运行实际窗口的 Qt 控件测试。
设置 `THEME_REVIEW_OUTPUT=build/theme-refactor/ui` 保存界面截图，再人工检查文字、边框、
悬停、按下、选中、禁用、菜单、弹窗和紧凑窗口布局。自动化同时核对实际设置、
Qt 调色板、影像和测量状态，不以点击被接受代替验证。
