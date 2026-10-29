# 四角直接编辑验证

四角信息设置由独立列表和预览改为同一个四角编辑区。名称和示例值一起显示，左右角分别采用左右对齐；示例数据不来自患者。每个角落有添加入口，可搜索字段；每行可删除、角内排序、跨角移动。

拖动时显示悬浮名称、目标角落和插入线。重复字段、已满 8 项的角落不允许放入，并显示原因。松手后源角落与目标角落一次写入配置；写入失败保留两端原值。Esc、页面隐藏、窗口失焦取消拖动。保留 Alt+上下键用于角内键盘排序。

原生 macOS Cocoa UI 测试使用真实 Qt 鼠标按下、移动及释放：横向、纵向跨角移动、空角落接收、角内排序、重复拒绝、Esc 取消、添加删除和配置重载；控制器测试验证数量上限、非法目标、无效插入位置及写失败原子性。截图检查了暗色及浅色窄窗口，修正了黑色示例区域在浅色主题下的文字对比度。

测试：`tests/test_corner_transfer.py tests/test_settings_redesign.py tests/test_workspace_interactions.py tests/test_display_settings.py`。日志和截图位于本地忽略目录 `build/favorite-directories/four-corners-regression.log`、`build/favorite-directories/four-corners/`。

手册与中、英、葡三语言说明同步更新。未执行打包发布或 Windows 原生验收。
