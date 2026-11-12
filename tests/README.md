# 测试与验证

`test_*.py` 为 pytest 回归用例，`qml/` 为测试使用的 QML 场景。`manual/test_*.py` 同样会被普通 pytest 和隔离 runner 递归收集，外部样本、原生桌面及 PACS 环境不满足时按用例条件跳过；目录名本身不会排除收集。`manual/` 内其他桌面检查、性能基准和 PACS 工具脚本需显式执行。所有命令均从项目根目录执行。

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  uv run --group dev python tests/run_isolated.py --timeout 300
```

## 桌面与性能检查

以下命令需要桌面会话；3D 检查还需要原生 OpenGL。使用合成数据，截图和基准输出放在临时目录。

```sh
uv run python tests/manual/smoke_3d.py /tmp/volume.png
# 可选：单个本地 CT 序列/时相的所有模板截图
uv run python tests/manual/render_ct_presets.py DICOM_DIR build/validation/ct-presets
uv run python tests/manual/smoke_pet_3d.py /tmp/pet-3d
uv run python tests/manual/smoke_water_qa.py /tmp/water-qa.png
uv run python tests/manual/benchmark_pet_locator.py /tmp/pet-locator.json
```

PET 基准使用接近实际规模的体积，需要足够内存。各项验收范围见 [三维编辑](../docs/volume-editing.md)、[PET 验证](../docs/validation/pet-fusion-workflow/README.md)和[水模 QA](../docs/water-qa.md)。

Windows 构建完成后，`manual/verify_windows_icons.py --icon <ICO> <EXE...>` 逐帧检查 PE 图标资源与品牌 ICO 一致，需要 build 依赖组；Windows 自动打包工作流会执行此检查。

## PACS 联调

入口为 `uv run python tests/manual/pacs_lab.py --help`。工具仍使用 `docker/pacs/` 下的 Compose、配置和产物目录，迁移不改变已有实验环境。启动服务及选择性运行端到端用例的步骤见 [PACS 联调说明](../docs/pacs-lab.md)。

## 专项分析与产物

一次性分析脚本与报告放在对应的 `docs/validation/<主题>/` 目录，额外科研依赖和原始数据要求由该报告说明，不加入应用运行依赖。例如本地 `spiral-mtf-slice11/` 中的 MTF 分析脚本与报告配套使用。

新增 pytest 用例放在本目录；新增手动验收工具放在 `manual/`；生成的临时图片、日志和缓存不放进 `scripts/`。`scripts/` 仅维护打包入口。

完整回归推荐使用隔离 runner，避免不同测试模块共享 Qt 全局对象；Windows 发布和安装包工作流统一使用 `uv run --group dev python tests/run_isolated.py`，逐文件启动独立 pytest 进程，保留全部用例。每个文件的输出、JUnit XML 与汇总写入 `build/test-results/`，失败或超时阻止打包；Actions 同时归档这些诊断资料。可传入测试文件路径执行局部复查；单个文件也可直接用 pytest。退出成功但缺失、空白或失败的 JUnit 记录也视为失败。

对明确要求全部执行的原生子集，添加 `--fail-on-skip`，任何跳过都会令该阶段失败并保留日志。默认仍允许环境相关的可选跳过；不要给包含其他平台用例、外部数据或可选系统权限的混合全集启用此选项。Windows 的更新 helper 包含 macOS 专属用例，导入 UI 包含可选目录符号链接能力，分别保留其跳过规则；必需的原生导入窗口、窗口控件、弹窗快捷键、PDF、工作区、QA 和 D3D 阶段单独禁止跳过。offscreen 全绿不代表原生字体、GPU 或外部联调已经完成。

Enhanced CT 多帧的公开原始样本、复跑命令与验收边界见 [Enhanced CT 测试数据](../docs/enhanced-ct-test-data.md)。合成用例为 `test_enhanced_ct.py`，外部样本与原生界面用例为 `manual/test_enhanced_ct_samples.py`。

显示映射回归：`tests/test_display_mapping.py` 覆盖数值／显示分离、源色还原、无效范围、实时预览、工作区状态与 QML；`tests/manual/test_display_mapping_samples.py` 使用文稿影像验证灌注、PET/CT 与 4D。详见 [显示映射](../docs/display-mapping.md)。

## 网站与旧工作区验收

网站部署前运行 `tests/test_manual_site.py`、`tests/test_manual_tasks_site.py` 和 `tests/browser/` 的浏览器检查。浏览器测试使用已生成的目录，覆盖中英文四种宽度及搜索/演示；依赖由 `tests/browser/package.json` 固定，截图和 JSON 报告作为 Actions 产物保留。

Windows 真实包迁移使用 `manual/verify_windows_package_updates.py --baseline tests/fixtures/upgrades/windows-baseline-v2.5.0.json`，仅允许一次性的 GitHub-hosted Windows runner。它固定旧包哈希并使用旧版本保存的合成非空工作区；候选包的 `--verify-workspace` 诊断检查真实恢复结果。该诊断不替代原生界面和旧客户端更新按钮操作；详细来源与边界见 fixture 的 `provenance.json`。
