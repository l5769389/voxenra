# UI 审核问题修复

依据 docs/validation/ui-logic-audit-20261029.md，用户已要求修复四项问题。

1. 将诊断探针转为 tests/test_ui_audit_regressions.py，验证预期行为并确认当前失败。
2. LocalImportDialog 用自身持有的单次 QTimer 合并收藏按钮定位，隐藏时停止。
3. ReorderTable 正确处理 WindowDeactivate/UngrabMouse，取消后释放不得保存，保留原选择。
4. FavoriteDirectoriesController 增加界面使用的异步验证入口和 busy 状态。后台仅检查路径，主线程重新验证数量、重复项和目标 ID 后保存；关闭界面取消请求，丢弃过期结果。对话框展示检查状态并禁用重复请求。现有同步内部接口保持兼容。
5. CornerLayoutEditor 示例绑定字号、行距、颜色；行高和拖动命中位置共用动态尺寸，测试外观变化及调整后的跨角拖动。
6. 运行 macOS Cocoa 界面操作和相关设置/收藏/导入回归，记录结果。不打包、不发布。
