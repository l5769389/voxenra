# main 合并验证（2026-10-29）

整合分支：`codex/reading-controls-20261028`、`codex/dicom-dimse`、`codex/update-verification-2.0.2`。后两个分支已是远端 main 的祖先；当前界面、收藏及四角编辑修改提交后，将本地 main 快进整合，没有内容冲突。补齐新 SVG/QML/JS 的 Qt 资源清单，`pyside6-rcc --list` 校验通过。

macOS Cocoa / software 后端，`tests/run_isolated.py` 完整运行 239 个文件，共 3,108 项。首轮 8 个失败：6 项仍使用旧对比页签英文长名称；1 项原生测量视口未取得焦点，HoverHandler 未进入，光标位置仍为 (0,0)；1 项 PACS 设置按钮点击后未出现编辑框。

更新对比页签的本地化断言；测量夹具增加 requestActivate / qWaitForWindowActive，确保鼠标事件作用于已激活窗口。PACS 未改动产品或测试逻辑，整文件两次复验均通过，保留首轮间歇性点击超时记录，不宣称其根因已修复。

最终复验上述四个文件 **79 passed**。以各文件最后一轮结果汇总：**3,033 passed、75 skipped、0 failures、0 errors**。这不是一次全绿的完整首轮执行。跳过项包含平台、额外原生验收及外部环境条件；不等同于 Windows 实机验收。

本地日志：`build/main-integration-20261029/full-tests/`、`final-recheck/`。原分支指向记录：`refs-before.json`。独立 DIMSE 工作目录保留，清理分支时切为 detached HEAD。仅在所有被删除分支提交已进入 main、并确认远端同步后删除冗余分支。未打版本标签或创建 Release。
