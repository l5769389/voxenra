# 工具栏视图分类验收（2026-10-28）

设置入口改为 2D 阅片、MPR 重建、3D、平铺、4D、融合六类。模式和图像类型位于默认折叠的细分选项中；当前完整配置名称始终显示。保留全部 26 个配置键，不迁移或合并已保存的工具顺序。

验证范围：

- 26 个具体配置均能通过主分类、模式和图像类型访问，分别保存；恢复默认只删除当前配置的覆盖值。
- 切换主分类保留本次选择与草稿，非法组合不改变配置。
- 从所属窗口最近影像初始化；真实第二窗口的影像／手册活动不改变存活编辑器的选择或草稿。
- 切换中、英、葡语言更新显示文字，同时保留配置与未保存顺序。
- 通过真实键盘和鼠标选择模式／图像类型、排序、保存，并从磁盘重新读取验证结果。
- Tab／Shift+Tab 可在细分选项与工具之间往返。
- 原生 macOS 800×600 界面中，展开选项后保存及恢复按钮保持可见，工具区域可滚动。

原生检查命令：

```sh
QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software .venv/bin/python -m pytest \
  tests/test_toolbar_categories.py -q --tb=short \
  --basetemp=build/toolbar-categories/native-final-checked \
  --junitxml=build/toolbar-categories/native-final-checked.xml
```

结果：11 passed。已检查 `native-final-checked/test_expanded_settings_fit_sma0/` 的三语界面截图；没有捕获到 QML 警告。Python 仅报告既有第三方 SWIG 弃用警告。

独立代码复核无剩余可操作问题；另行运行的检查确认了 390×520、390×600、540×600 编辑区域边界，以及键盘往返和三语切换。既有设置页面卸载时的草稿生命周期保持不变，本轮验证只要求其他窗口活动不能重置仍存活的编辑器。

完整隔离回归：

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  .venv/bin/python tests/run_isolated.py --output build/toolbar-categories/full
```

结果：234 个测试文件全部成功；3058 个用例中 2976 passed、82 skipped、0 failures、0 errors。跳过项沿用项目的环境／可选集成条件。结果文件为 `build/toolbar-categories/full/results.json`，逐文件日志和 JUnit XML 位于同目录。本次整套检查也包含此前未提交的工具栏拖拽和主页图片压缩改动。

`git diff --check` 通过。所有改动仍在本地，未提交或发布。
