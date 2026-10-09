# macOS 签名流程验证（2026-10-09）

## 已完成

- 新增正式模式和只检查配置模式；精确匹配 Developer ID Application 身份，提前校验公证认证。
- 应用及 DMG 分别公证、装订票据并进行 Gatekeeper 检查。拒绝、无效返回和工具失败均终止；最终 DMG 仅在所有步骤成功后替换。
- 更新本地配置教程、打包文档和发布清单。未提交、打包 Voxenra 或上传发布附件。

## 验证

- `test_macos_signing.py` 11 项、`test_installers.py` 10 项、`test_windows_packaging.py` 12 项、`test_packaging_qml_hook.py` 4 项全部通过。签名流程测试替代外部 Apple 命令，核对失败分支、执行顺序及文件替换，不等同于真实公证。
- `test_update_installer.py` 首次在沙箱中运行：5 项在 `hdiutil create` 处失败。允许原生磁盘映像操作后重新运行：7 通过、4 个 Windows 平台测试跳过。覆盖临时 DMG 更新、校验错误、替换失败、启动失败与超时回退；未修改已安装的 Voxenra。
- 去重后本轮相关回归：44 通过、4 跳过。原始结果在 `build/macos-signing-validation/results.json`，原生更新复测在同目录 `update-native.xml`。
- 本机 `notarytool`、`stapler` 可用；`security find-identity -v -p codesigning` 返回 0 个有效身份。真实运行 `--check-signing` 在缺失证书时返回非零，未开始构建或上传。
- `git diff --check` 通过。

## 未验证

用户尚未开通 Apple Developer Program，也未配置证书。真实 Developer ID 签名、Apple 公证受理、票据装订、正式包 Hardened Runtime 兼容性及另一台 Mac 的 Gatekeeper/离线安装仍待配置后执行。不能将上述脚本测试表述为“安装包已通过 Apple 公证”。
