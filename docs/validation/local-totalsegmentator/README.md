# 本地 TotalSegmentator 基础集成验证

日期：2026-10-10 至 2026-10-12。范围为当前源码；未打包、发布、提交或推送。

## 实现范围

- 设置 → 服务工具 → 本地自动分割：外部 Python、模型目录、后台检测、设备选择与持久化。自动识别本机 `TotalSegmentator-Local`。
- CT MPR / 4D 分割面板的自动分割图标：搜索、多选、全选、清空；初始肝脏、脾脏、双肾。稳定英文标识传给模型，界面有中英文名称。
- CT 快速模型 297，`fast=True, robust_crop=True`；自动设备顺序 CUDA → MPS → CPU。独立运行配置关闭统计，推理期间阻止网络请求；不安装或下载依赖/权重。
- 主程序不导入 torch、TotalSegmentator 或 NIfTI 依赖；桥接脚本作为数据资源，由外部 Python 执行。
- 从已加载的当前时相完整 HU 体数据导出 NRRD。验证规则正交网格、完整器官输出、二值掩膜和所有角点 ≤0.001 mm 的几何误差；不以重采样修正错误输出。
- 单任务、阶段显示、取消与进程树清理；目标变更拒绝回填，切换时相/编辑中暂存。全部验证后一次追加，沿用分割精修、统计、显隐、配色、整批撤销和工作区保存。
- 工作区保留器官、模型、TotalSegmentator 版本、设备、时间、来源指纹/时相及掩膜；恢复不需要模型、不重新推理。

## 真实运行和空间核对：通过

环境：Apple M5，TotalSegmentator 2.18.0，Apple MPS；Slicer 5.12.4。
输入：本地既有 P113 CT，512 × 512 × 99，间距约 0.9766 × 0.9766 × 3 mm。原始数据、完整日志和掩膜仅在本地忽略目录中。

Voxenra 实际扫描、建立 MPR、准备数据、推理、校验并回填四器官。本次已热缓存的实例，从加载开始至回填约 39.6 秒；这是单例记录，不代表其他影像或机器的速度。

| 器官 | 体素数 | 与独立运行的不同体素数 |
|---|---:|---:|
| 肝脏 | 505614 | 0 |
| 脾脏 | 86281 | 0 |
| 左肾 | 24351 | 0 |
| 右肾 | 29305 | 0 |

独立结果与 Voxenra 数组轴方向不同，先按患者坐标做轴置换/翻转，未插值。输入数值、返回四器官掩膜逐体素相同，几何通过。

Slicer 直接读取 Voxenra 输出的 source.nrrd 和 segmentation.seg.nrrd：

- 体素值、LPS/RAS 转换后的空间矩阵、四个二值掩膜、名称与颜色一致。
- 在 Slicer 中修改第一个掩膜的 `[1,2,3]` 体素并改名，导出后由 Voxenra 的实际 NRRD 入口读取：四个掩膜（含该编辑点）完全一致。
- 此次比较验证交换与网格正确性；没有把 Slicer 当作分割解剖准确性的真值，也没有重新做 Slicer Segment Statistics 数值审核。

## 产品闭环：通过

- 实际保存 `.voxworkspace`，在另一进程重新打开：四个掩膜、偏移和自动分割元数据一致，没有启动推理。
- 可见界面操作：搜索 `kidney` 能匹配双肾及肾囊肿；启动后按钮变为取消；取消不增加分割。
- 画笔修改已恢复的肝脏：体素数 505614 → 505700；撤销回到 505614，重做回到 505700，其他三个器官不变。最后撤销该测试编辑。
- 自动化实际 4D 页签：原时相请求的结果在另一时相暂存，回原时相才导入；不改变切片位置，其他时相的显示列表及掩膜保持独立。
- 新批次追加、原有分割保留、整批撤销重做、重复启动、过期完成事件、关闭目标、取消、配置更改等测试通过。

## 界面和自动化

- 桌面可见检查：1440 × 900 逻辑窗口，中性深灰中文结果叠加、中文器官对话框、浅色英文器官对话框、深色英文服务设置。未见新增区域遮挡。
- QML 自动化覆盖三主题/中英文、1280 × 720 窗口，以及 240/300/420 侧栏配置下的对话框尺寸和器官选择；无 QML 警告。
- 最后重启到小窗口后，桌面工具重新绑定应用超时，**该次小窗口的桌面可见检查未完成**；上述自动化不冒充这项人工可见验收。
- 合成 NRRD → NIfTI → NRRD：非对称强度场、轴置换、反向层序、各向异性和斜位组合，像素完全一致、角点误差在 0.001 mm 内。
- 覆盖缺少 Python/模型、依赖错误、中文及空格路径、崩溃、超时、实际子进程取消、空器官、部分输出、非二值/错位结果拒绝。

完整隔离回归：187 个测试文件，2473 项通过、71 项依赖/平台条件跳过，无失败。随后新增 4D/异常目标等检查，以及错误详情和资源清单调整，最终相关测试 51 项通过，无失败，记录在本地 `build/local-segmentation/final-check.log`。

## 复审修复

1. Windows 父进程先退出时可能留下推理子进程：改为先挂起启动，归属 kill-on-close Job Object 后恢复运行；关闭任务对象清理整棵进程树。自动化覆盖归属/恢复/关闭顺序，Unix 另有真实子进程取消测试。
2. 写诊断日志失败可能跳过影像清理：日志读写与清理分离，清理放在无条件 finally 中；模拟磁盘写入失败后任务目录仍被删除。
3. 环境检测期间配置变更：过期检测结果不能标为可用。
4. 关闭目标释放控制器保留的体数据；不启用持久设置的测试实例使用独立临时缓存，避免影响用户缓存和启动。
5. 无效目标的错误不再被自动环境检测覆盖，开始按钮在没有有效目标时禁用。

## 明确未验证 / 不支持

- Windows 实机、CUDA 实机、其他 TotalSegmentator 版本：未实机验证，不能据模拟进程测试宣称已验收。
- 真实 4D 影像的长耗时推理与操作并发尚未桌面实测；实际 4D 控制器/扫描数据的延迟回填已自动化覆盖。
- 全部 117 个结构没有逐一做真实推理或解剖准确性评估；真实运行限上述四器官和一个 CT 样本。
- MR、普通 2D、非 HU 派生图、剪切/不规则网格、高精度和云端服务不在首版范围。

## 复运行

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m pytest tests/test_local_segmentation*.py -q
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python tests/run_isolated.py --output build/local-segmentation/regression
```

本机外部环境转换测试默认探测 `~/Applications/TotalSegmentator-Local/venv/bin/python`，也可设置 `VOXENRA_TOTALSEG_PYTHON`；不存在时明确跳过。

真实任务（使用隔离设置；窗口保持打开供 GUI 操作）：

```sh
.venv/bin/python tests/manual/verify_local_segmentation.py CT_DIRECTORY OUTPUT_DIRECTORY --run
.venv/bin/python tests/manual/verify_local_segmentation.py OUTPUT_DIRECTORY/automatic.voxworkspace REOPEN_OUTPUT --restore
```

该脚本输出 `expected.npz`，供现有 `tests/manual/verify_nrrd_slicer.py` 在独立 Slicer 实例中验证。设置 `VOXENRA_NRRD_QA=OUTPUT_DIRECTORY`，用 Slicer 的 `--disable-settings --ignore-slicerrc --python-script` 启动该脚本，保留用户原来的 Slicer 场景。

```sh
EXTERNAL_PYTHON tests/manual/compare_local_segmentation.py OUTPUT_DIRECTORY --standalone INDEPENDENT_RESULT_DIRECTORY
.venv/bin/python tests/manual/compare_local_segmentation.py OUTPUT_DIRECTORY --slicer-return
```

机器可读本地证据位于 `build/local-segmentation/native-final/`，界面和画笔证据位于 `build/local-segmentation/gui/`。这些数据不加入仓库。

## 2026-10-12：环境配置和设置页复核

- 设置页改为独立环境状态、模型/版本状态、计算设备和默认收起的高级配置；路径仅在悬停提示显示。分割取消或失败不覆盖环境检测状态。
- 自动发现覆盖专用安装目录、常见 Conda 根目录/环境登记文件、活动环境及 PATH 中的解释器，要求存在 TotalSegmentator 包。Windows 区分 venv 的 `Scripts/python.exe` 与 Conda 的环境根 `python.exe`；手动路径优先，不用自动发现掩盖失效的显式路径。自定义/可编辑安装仍可手动指定。
- 模型目录支持选择 results、Dataset297、训练器或 fold 目录，统一传入模型根目录；检查配置 JSON 可解析且非空，并在详情记录缺失文件。检测没有加载全部权重或执行推理，不等于模型完整性/显存验收。
- 保存的不可用设备保持原值并明确标识，禁止以界面上的“自动”掩盖实际设备。自动模式显示将使用的设备。
- 版本/平台/设备组合区分已验证的 2.18.0 macOS/MPS 与接口通过但未实测的组合；仍拒绝不兼容接口和 CT 快速模型。不宣称未知未来版本全部兼容。
- 原生 GUI 实测发现 macOS 文件选择器会将 venv Python 符号链接解析成底层 Python，导致丢失环境。添加 `DontResolveSymlinks`，修复后再次通过原生选择器选择，隔离设置实际保存 `TotalSegmentator-Local/venv/bin/python`，检测成功。
- 可见界面检查：1280 × 720 逻辑窗口，英文中性深灰、中文浅色；高级配置展开/收起、解释器选择、检测结果与自动 MPS 显示均正常。QML 自动化另覆盖中英文和三主题，以及已保存 CUDA 在 CPU-only 环境下明确显示不可用。
- 相关 10 个测试文件共 88 项通过，无失败/跳过；后续符号链接修复后重新运行控制器、环境发现和 QML 共 33 项通过。日志位于本地 `build/local-segmentation/settings-check/` 和 `settings-final.log`。有 3 条第三方 SWIG 弃用警告，无新增 QML 警告。
- Windows 目录发现与进程分支为自动化验证，Windows/CUDA 实机验收仍未完成。本轮未重做四器官推理，未变更推理公式或分割回填路径；未打包、发布、提交或推送。

## 2026-10-12：通过原生界面重跑完整流程

使用本机 TotalSegmentator 2.18.0、MPS、CT 快速模式，输入为已有 P113 CT 的 99 张切片。在独立设置目录、1440 × 900 逻辑窗口中运行，原始影像及用户工作区未修改。测试夹具只预加载 CT 并被动采集状态；环境检测、设备选择、推理启动、精修、保存、退出和重新打开均通过桌面界面操作完成。

### 发现并修复

重新检测环境后，设备下拉框可能从手动 MPS 错误显示为“自动 (MPS)”，而底层保存值仍为 `mps`。原因是 Qt ComboBox 在替换选项模型后重置索引；原绑定的计算值未变化，未重新应用索引。现在在选项模型更新完成后按保存值恢复选择，且不会写回或改变计算设备。

- 新增回归用例先复现失败，再验证修复；覆盖检测刷新、重复刷新、CPU 切换与不可用 CUDA 的显示。
- 修复后重新启动原生应用，重新检测实际外部环境，界面保持“MPS”，配置仍为 `mps`。

### 实际结果

| 阶段 | 肝脏体素数 | 脾脏 | 左肾 | 右肾 | 核对 |
|---|---:|---:|---:|---:|---|
| 自动分割 | 505614 | 86281 | 24351 | 29305 | 与此前独立运行的计数一致 |
| 整批撤销 | — | — | — | — | 四个记录全部移除 |
| 整批重做 | 505614 | 86281 | 24351 | 29305 | 掩膜哈希、ID、颜色、来源元数据与撤销前一致 |
| 画笔测试笔画 | 505682 | 86281 | 24351 | 29305 | 仅所选分割增加 68 体素 |
| 橡皮擦除笔画 | 505634 | 86281 | 24351 | 29305 | 仅所选分割减少 48 体素 |
| 保存后退出、重新打开 | 505634 | 86281 | 24351 | 29305 | 四个掩膜及全部记录字段完全一致 |

画笔与橡皮分别执行撤销、重做，均恢复到对应操作前后的精确掩膜。笔画用于验证编辑行为，不是对器官边界作医学修正。可见叠加、列表及统计与记录吻合；本次没有进行高帧率录屏或量化流畅度测试。

保存通过原生文件对话框完成，保存后 `dirty=false`。退出应用，以相同隔离设置重新启动为空白工作区，通过“最近工作区”打开保存文件：

- 四个掩膜逐体素相同，偏移、ID、名称、颜色、可见性以及模型/版本/器官/时间/来源字段递归比较全部相同。
- 恢复到“分割 → 橡皮”、5 mm、原选中的肝脏，切片位置及叠加正常。
- 恢复完成时无缺失来源、无忙状态、无虚假未保存状态；推理控制器保持 `idle`，未重新计算。
- 手动选择的 MPS 与器官列表重启保留；再次检测后环境可用。环境检测状态本身不从磁盘冒充已验证结果。
- 无新增 QML 警告。此次未复现其他阻断该闭环的问题。

最终相关回归 **121 项通过**，无失败或跳过；3 条第三方 SWIG 弃用警告。命令：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_local_segmentation*.py tests/test_mpr_voi_controller.py tests/test_workspace_persistence.py tests/test_workspace_tool_selection.py tests/test_display_settings.py -q
```

被动采集模式可用 `tests/manual/verify_local_segmentation.py SOURCE OUTPUT --interactive`；重启时追加 `--empty`，再从界面打开工作区。它不会自动启动推理、编辑或保存。重用 OUTPUT 前应保留上一次采集文件，以免覆盖编号快照。

本地证据：`build/local-segmentation/flow-20261012/`，包含 `edited.voxworkspace`、`before-restart/` 的快照/计数/哈希历史及 `restore-verification.json`。不纳入仓库。

结论限于本机 macOS/MPS、该 CT 和四器官闭环。此次未重新运行 Slicer 对照，也未做 Windows/CUDA 实机、全部器官或真实 4D 推理验收；此前交换验证不能代替这些检查。未打包、发布、提交或推送。

## AI 设置独立与文档核对（2026-10-12）

- 自动分割环境配置移至独立的“设置 → AI”，服务工具保留 MTF/FWHM。保留原持久化键兼容已有环境路径、设备和器官选择；两页恢复默认互不影响。
- 部位选项来自所选 Python 环境的 `totalsegmentator.map_to_binary.class_map['total']`。环境检测刷新可支持结构，中英文名称由 Voxenra 映射，未知名称回退英文；该列表不表示影像中的已检出器官。
- 原生隔离应用中搜索并进入 AI 页面，点击检测环境：显示 TotalSegmentator 2.18.0、CT 快速模型可用，保存的 MPS 选择保留。进入服务工具确认没有自动分割配置。
- 更新中英文 README、内置教程和生成主页。主页以开发版标记新增 AI 能力，下载仍指向 v2.0.1；中英文教程链接及部位来源文字经本地浏览器核对，窄屏下新增介绍无截断。
- 回归两批分别 **59 项通过**（设置、自动分割 QML、手册、网站及打包资源钩子）和 **53 项通过**（自动分割 QML、设置 QML 和设置布局，含独立内容测试），存在重复执行项，不将两批相加作为独立用例数。均仅有 3 条第三方 SWIG 弃用警告。
- 本轮未重新推理、未进行 Windows 实机检查、未打包或部署网站。

## AI 展示素材录制（2026-10-12）

- 再次通过隔离原生界面完成 CT 四器官推理，TotalSegmentator 2.18.0 / MPS。肝脏、脾脏、左肾、右肾分别为 505614、86281、24351、29305 体素，与此前计数一致；本次不以计数一致代替逐体素空间验证。
- 录制器官搜索、选择、启动、完成、三平面结果、画笔编辑和撤销。测试笔画使肝脏增加 16 体素，撤销后恢复原计数，其他三项未变。未保存覆盖原工作区。
- `docs/screenshots/39-ai-segmentation.gif` 为真实应用窗口关键帧编码，1440 × 900、13 帧、21.8 秒、约 3 MB；推理等待已压缩，文案明确不是实时速度展示。另提供最终结果 PNG。没有拼接其他应用界面或合成分割效果。
- 原始帧及 SHA-256 清单位于本地 `build/ai-demo-20261012/`，不加入仓库。中英文主页实际检查默认桌面和 390 px 窄屏，AI 动图加载正常，窄屏无横向溢出；网站测试 3 项通过。
- README 和主页突出本地 AI / TotalSegmentator，保留开发版标记及 v2.0.1 下载边界。GitHub About 与相关 topics 已更新；未提交、推送或部署网站。
