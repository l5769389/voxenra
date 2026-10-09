from pathlib import Path

import pytest

from qt_dicom_viewer.core.release_notes import summarize_release_notes, validate_release_notes


NOTES = '''# Voxenra 2.1.0

## 更新摘要
- 新增鼠标设置。
- 优化分割预览。

## Update summary
- Customize mouse controls.
- Faster segmentation previews.

## 完整说明
- Implementation and test details.
'''


def test_summary_selects_language_and_excludes_details():
    assert summarize_release_notes(NOTES, 'zh-CN') == '• 新增鼠标设置。\n\n• 优化分割预览。'
    assert summarize_release_notes(NOTES, 'en-US') == '• Customize mouse controls.\n\n• Faster segmentation previews.'
    assert summarize_release_notes(NOTES, 'es-ES') == summarize_release_notes(NOTES, 'en-US')
    assert validate_release_notes(NOTES) == []


def test_legacy_release_is_clean_and_bounded():
    notes = Path('docs/releases/v2.0.0.md').read_text()
    # Exercise the retained legacy body, even when a release is later amended
    # with the new summary headings.
    notes = '## 新增与改进' + notes.split('## 新增与改进', 1)[1]
    summary = summarize_release_notes(notes, 'zh-CN')
    assert '**' not in summary and '##' not in summary
    assert '验证' not in summary and 'English' not in summary
    assert 1 <= summary.count('• ') <= 6
    assert 'Voxenra 2.0.0 adds' in summarize_release_notes(notes, 'en-US')


def test_external_content_is_plain_text_without_images_or_links():
    notes = '## 更新摘要\n- **修复** [滚动](https://example.com)。\n- ![image](https://example.com/image.png)\n- <img src="https://example.com/tracker">\n- `Ctrl+Z` 可撤销。'
    assert summarize_release_notes(notes, 'zh-CN') == '• 修复 滚动。\n\n• Ctrl+Z 可撤销。'


def test_empty_and_plain_legacy_notes():
    assert summarize_release_notes('', 'en-US') == ''
    assert summarize_release_notes('A plain release note.', 'en-US') == '• A plain release note.'
    assert summarize_release_notes('## 更新摘要\n- 中文。', 'en-US') == '• 中文。'


@pytest.mark.parametrize('notes', [
    NOTES.replace('## Update summary', '## English'),
    NOTES.replace('## 更新摘要', '### 更新摘要'),
    NOTES.replace('- 新增鼠标设置。', '- **新增**鼠标设置。'),
    NOTES.replace('- 新增鼠标设置。', '- ' + '字' * 81),
    NOTES.replace('- 优化分割预览。', '\n'.join('- 改进。' for _ in range(6))),
    NOTES.replace('- 新增鼠标设置。', '没有使用列表。'),
])
def test_release_format_validator_rejects_unbounded_or_formatted_summaries(notes):
    assert validate_release_notes(notes)
