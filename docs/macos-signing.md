# macOS Developer ID 签名与公证

Voxenra 通过官网／GitHub 分发 DMG，采用 Developer ID Application 签名和 Apple 公证，不要求上架 Mac App Store。会员资格本身不会自动签名已有安装包。

## 一次性配置

1. 开通 [Apple Developer Program](https://developer.apple.com/programs/)，完成账号验证及相关协议。
2. 在 Xcode 的 Settings → Accounts 中登录开发者账号并选择团队，通过 Manage Certificates 创建 **Developer ID Application** 证书；也可按 Apple 开发者网站的证书流程创建并导入。签名需要证书及其配对私钥，只有 `.cer` 文件不够。组织账号可能需要 Account Holder 操作。
3. 在“钥匙串访问”的“我的证书”中确认该证书下有私钥，然后在终端查看有效签名身份：

   ```bash
   security find-identity -v -p codesigning
   ```

   选择完整的 `Developer ID Application: … (TEAMID)` 名称，或对应 SHA-1；不要使用 Apple Development、Apple Distribution 或 Developer ID Installer。

4. 保存公证凭据到本机钥匙串。在终端执行以下命令，按交互提示输入 Apple ID、Team ID 和 **App 专用密码**：

   ```bash
   xcrun notarytool store-credentials "voxenra-notary"
   ```

   App 专用密码在 Apple Account 网站创建，不是账号登录密码。不要把密码、私钥、证书导出文件或 API 私钥发到聊天、写入仓库或放入命令行参数。工具也支持 App Store Connect API 密钥，按 Apple 官方说明配置即可。

## 检查与构建

在本机终端设置非秘密的身份名称和钥匙串配置名：

```bash
export MACOS_SIGN_IDENTITY='Developer ID Application: YOUR NAME (TEAMID)'
export MACOS_NOTARY_PROFILE='voxenra-notary'

# 只验证本地证书、工具及 Apple 认证；不构建、不上传应用。
bash scripts/build_macos.sh --check-signing

# 按发布检查清单验收对应提交后，生成正式签名并公证的安装包。
bash scripts/build_macos.sh --release
```

检查认证需要联网。macOS 可能弹出私钥访问提示，由证书持有人在本机处理。脚本不会导出私钥或读取凭据明文。

正式模式按顺序执行：

1. 检查唯一有效的 Developer ID 身份及公证配置，失败即停止。
2. PyInstaller 签署收集的二进制与依赖；启用 Hardened Runtime 和安全时间戳。修改应用版本后重新签署外层应用，保留原有 entitlements，不添加未经验证的安全例外。
3. 深度验证代码签名；将应用 ZIP 提交 Apple，明确检查 `Accepted`，给 `.app` 装订票据，验证票据与 Gatekeeper。
4. 将已装订的应用放入临时 DMG；签名、公证、装订并验证 DMG。全部通过才替换 `dist/installers/` 中的最终 DMG。失败不覆盖上一份安装包。
5. 按[发布清单](release-checklist.md)执行实际启动与安装检查，之后生成 SHA-256。脚本不自动提交代码或上传 GitHub Release。

不带正式签名参数的构建仍可用于本地测试，但 ad-hoc 签名不等于 Apple 信任认证。已有公开包不能因本机新增证书而自动获得公证；后续需发布新版本，不能悄悄替换旧版附件及校验值。

## 结果与限制

Apple 返回值及公证日志位于 `build/macos/notarization/<版本>-<架构>/`。公证拒绝、网络失败、票据或 Gatekeeper 检查失败都会使命令返回非零状态；不能根据目录中仍存在旧 DMG 判断本次成功。

完成脚本接入并不等于产物已获 Apple 认可。首次配置后仍需实测正式包的 QML、Python 扩展、Qt/VTK 插件、文件访问及自动更新；若 Hardened Runtime 暴露兼容问题，先根据日志定位，不直接关闭库校验等保护。

在另一台未运行过 Voxenra 的 Mac 上，从正式下载链接获取 DMG（保留正常下载隔离属性），断网安装并启动，确认无需“设置 → 仍要打开”。正常的“来自互联网，是否打开”确认以及机构管理策略仍可能存在。

参考：[Apple Developer ID](https://developer.apple.com/developer-id/)、[公证流程](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)、[PyInstaller macOS 签名](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)。
