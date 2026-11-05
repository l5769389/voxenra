# Voxenra X.Y.Z

发布日期：YYYY-MM-DD · 用一句话说明本版最重要的用户收益。

## 更新摘要

- 升级：如需手动升级、迁移数据或注意兼容变化，明确适用版本及操作；无此事项则删除本条。
- 新增：说明用户现在可以完成什么。
- 改进：说明现有功能的具体体验变化。
- 修复：说明什么操作下的问题已解决。

## Update summary

- Upgrade: state affected versions and required action for a manual upgrade, migration, or compatibility change; omit if none.
- Added: describe a new action available to users.
- Improved: describe a concrete change to an existing workflow.
- Fixed: describe the user-visible problem and when it occurred.

## 中文说明

### 升级须知

填写适用的旧版本、用户需要采取的操作及下载或迁移说明链接。核对工作区、设置及新旧版本读取范围；没有需要用户行动的变化时明确写出或省略此节，不作未经验证的兼容承诺。

### 主要改进

按用户任务分组，每项说明功能变化及用途。功能大版本可添加一至两张与本版代码对应的截图；修复版不强制配图。具体按键表和逐步操作链接到对应版本手册。

### 行为变化与问题修复

- 行为变化：写清原来的行为、现在的行为，以及如何继续原有工作。
- 问题修复：写清触发场景和修复后的表现，避免内部类名、提交标题及笼统的「全面优化」。

### 安装兼容性与已知限制

列出实际提供的系统、架构与包类型，以及签名、公证或功能限制。区分已知问题与未验证场景。尚未验证的性能、精度、兼容性和平台流程不得写成通过。

### 相关资料

提供本版操作手册、完整版本差异及发布验收记录的有效链接。测试数量、日志和内部实现细节留在验收记录或技术变更中。

## English details

Released YYYY-MM-DD. Describe the main user benefit in one sentence.

### Upgrade notes

State affected versions, required actions, and relevant download or migration links. Match the Chinese compatibility claims and limitations.

### Improvements

Group changes by user workflow. Link detailed instructions to the manual for this version. Add screenshots only when they clarify a substantial visual change.

### Behavior changes and fixes

Explain changed behavior and how to continue previous work. Describe fixes through the affected user action and resulting behavior.

### Installation, compatibility, and known limitations

List actual platforms, architectures, package types, signing status, and limitations. Distinguish known defects from scenarios that remain unverified.

### Related resources

Link the versioned manual, full comparison, and release validation record.

<!-- 编辑约束（正式发布前删除本注释及所有占位文字）：
1. 保留两个固定二级摘要标题，每种语言 1–6 条单行普通 - 列表。
2. 中文每条 <=80 字符，英文 <=180；摘要不放粗体、链接、图片、嵌套列表或测试日志。
3. 必须采取行动的升级事项应进入摘要；合并或下移次要改动，不能挤掉升级提醒。
4. 中文与英文事实、行为和限制一致；完整说明按语言成块，不逐段交替。
5. 只说明发布标签中的变化。旧版说明修订不得加入后续开发版功能，也不替换旧附件。
6. 发布前运行 scripts/check_release_notes.py，并按 docs/release-checklist.md 验证最终提交。
-->
