# VoxPlane 2.7.0 发布验收

本版基于 v2.6.0。候选提交固定后重新执行完整回归、受影响原生界面、macOS 打包和 Windows Actions。最终运行、包哈希与跳过原因在发布后的验收补充中记录；本文件不预先宣称尚未执行的检查通过。

| 用户要求 | 实现与验收入口 |
| --- | --- |
| 显示默认值与具体窗值 | initial_display / presets_settings_qml / mr |
| 截图预设、实际预览、保存相同内容 | screenshot_presets / screenshot_preview / export_presets |
| 报告选项、窄设置栏与大预览 | report_presets / report_dialog_qml / presets_settings_qml |
| 镜像、旋转、重置与测量 | measurement_qml / free_rotation_qml / annotation_clipboard |
| 菜单内快捷键与弹窗隔离 | reading_menu_shortcuts / popup_shortcut_isolation |
| QA 撤销恢复与实际圆尺寸 | qa_audit_regressions / water_qa_qml |
| MPR 半体素画笔 | segmentation_half_voxel / segmentation_render_cache |
| 教程与主页 | manual_tasks / manual_tasks_site / manual_site / 浏览器布局与任务导航 |
| 固定构建提交与不可变正式附件 | windows_release_integrity / package_upgrade_gate / Windows provenance |
| 旧工作区与设置迁移 | packaged_workspace_check / pinned baseline Windows package upgrade |

本版保留现有工作区格式，不修改 MTF、FWHM、QA 计算算法。macOS 为 ad-hoc 签名且未公证；Windows 无 Authenticode 签名。外部 PACS、可选影像样本、其他硬件及原生平台测试按实际执行范围分别记录。
