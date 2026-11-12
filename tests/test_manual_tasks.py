"""Reader-facing search/navigation semantics, independent of Qt rendering."""

def sample():
    return [dict(id='qa',title='QA',summary='Quality',sections=[
        dict(title='空气取样',body='添加空气 ROI，检查有效像素。'),
        dict(title='保存',body='按 Ctrl+S 保存工作区。')]),
        dict(id='other',title='Other',summary='',sections=[dict(title='参考',body='空气 ROI 也可查看。')])]


def test_section_search_ranks_titles_and_requires_all_terms():
    from voxplane.core import manual_index
    result = manual_index.search_sections(sample(), '空气 ROI', limit=10)
    assert [r['chapterId'] for r in result] == ['qa','other']
    assert result[0]['sectionIndex'] == 0
    assert result[0]['sectionId'] == 'step-1'
    assert '添加空气' in result[0]['snippet']
    assert manual_index.search_sections(sample(), '空气 absent') == []


def test_search_shortcuts_casefold_limit_empty_and_literal_markup():
    from voxplane.core import manual_index
    assert manual_index.search_sections(sample(), 'ctrl+s')[0]['sectionIndex'] == 1
    assert len(manual_index.search_sections(sample(), '空气',limit=1)) == 1
    assert manual_index.search_sections(sample(), '  ') == []
    data=sample();data[0]['sections'][0]['body']='literal <img onerror=x> & ROI'
    assert '<img onerror=x>' in manual_index.search_sections(data,'onerror')[0]['snippet']


def test_neighbor_boundaries_and_explicit_stable_anchor():
    from voxplane.core import manual_index
    assert manual_index.chapter_neighbors(sample(),'qa') == (None,'other')
    assert manual_index.chapter_neighbors(sample(),'other') == ('qa',None)
    assert manual_index.section_id({'id':'air-sampling'},3) == 'air-sampling'
    assert manual_index.section_id({},3) == 'step-4'


def test_task_catalog_and_search_select_exact_section():
    from voxplane.ui.controller.manual_tab_controller import ManualTabController
    c = ManualTabController()
    assert len(c.taskRoutes) == 5
    c.setSearch('空气 ROI')
    results = c.searchResults
    result = next(r for r in results if r['chapterId'] == 'qa-air' and r['sectionIndex'] == 1)
    c.selectSection(result['chapterId'], result['sectionIndex'])
    assert c.chapterId == 'qa-air' and c.sectionIndex == 1
    assert c.currentChapter['outcome']
    c.selectSection('qa-air', 999)
    assert c.sectionIndex == 1
    c.setSearch('impossible-no-match')
    assert c.searchResults == []
    c.setSearch('')
    assert c.searchResults == []
    c.selectTasks()
    assert c.showTasks
    c.selectChapter('quick-start')
    assert not c.showTasks

from test_pacs_qml import scene
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import find, click
from PySide6.QtCore import QPointF


def test_reader_search_click_lands_on_visible_section(scene):
    window, app, warnings = scene
    app.workspaceController.openManual('quick-start')
    c = app.workspaceController.manualController
    c.setSearch('空气 ROI')
    wait_until(lambda: find(window, 'manualTaskSearch-qa-air-1') is not None)
    button = find(window, 'manualTaskSearch-qa-air-1')
    # Navigation list may need scrolling; item must be a real clickable target.
    nav = find(window, 'manualTaskSearchScroll')
    nav.setProperty('contentY', max(0, button.mapToItem(nav.property('contentItem'), QPointF()).y()-10))
    click(window, button)
    wait_until(lambda: c.chapterId == 'qa-air')
    wait_until(lambda: not find(window, 'operationManual').property('restoring'))
    section=find(window,'manualSection-1');reading=find(window,'manualReadingArea')
    assert 0 <= section.mapToItem(reading,QPointF()).y() < reading.height()
    assert not [w for w in warnings if 'ReferenceError' in w or 'TypeError' in w]


def test_task_home_does_not_reuse_or_overwrite_reading_position():
    from voxplane.ui.controller.manual_tab_controller import ManualTabController
    c = ManualTabController()
    c.setScrollPosition(350)
    c.selectTasks()
    assert c.scrollPosition == 0
    c.setScrollPosition(120)
    assert c._positions['quick-start'] == 350


import os
from pathlib import Path
import pytest
from PySide6.QtTest import QTest
from test_tag_qml import descendants


@pytest.mark.parametrize('theme,locale,size', [('dark','zh-CN',(1440,900)), ('light','en-US',(1000,600)), ('graphite','zh-CN',(1280,720))])
def test_task_home_live_language_and_narrow_controls(scene, monkeypatch, tmp_path, theme, locale, size):
    from test_window_sizing import fit_desktop
    window, app, warnings = scene
    fit_desktop(window, app, monkeypatch, size)
    if os.environ.get('QT_SCALE_FACTOR') == '1.3':
        assert abs(window.devicePixelRatio() - 1.3) < 0.01
    app.settingsController.setValue('appearance','theme',theme)
    app.workspaceController.openManual('quick-start')
    c=app.workspaceController.manualController
    c.selectTasks()
    app.languageController.selectLanguage(locale)
    wait_until(lambda: not find(window,'operationManual').property('restoring'))
    assert c.taskRoutes[0]['title'] == ('第一次阅片' if locale=='zh-CN' else 'First reading')
    c.setSearch('ROI')
    assert len(c.searchResults)==31
    if locale=='en-US':
        assert all('空气' not in r['title'] for r in c.searchResults)
    c.setSearch('')
    evidence=Path(os.environ.get('MANUAL_TASK_EVIDENCE',str(tmp_path)))
    evidence.mkdir(parents=True,exist_ok=True)
    QTest.qWait(60)
    assert window.grabWindow().save(str(evidence/f'tasks-{theme}-{locale}.png'))
    c.selectChapter('point-mtf')
    wait_until(lambda: not find(window,'operationManual').property('restoring'))
    QTest.qWait(60)
    assert window.grabWindow().save(str(evidence/f'mtf-guide-{theme}-{locale}.png'))
    assert not warnings, warnings


def test_keyboard_search_keeps_focused_result_in_view(scene):
    from PySide6.QtCore import Qt
    window, app, warnings=scene
    app.workspaceController.openManual('quick-start')
    c=app.workspaceController.manualController
    c.setSearch('ROI')
    first=c.searchResults[0]
    hit=find(window,f'manualTaskSearch-{first["chapterId"]}-{first["sectionIndex"]}')
    scroller=find(window,'manualTaskSearchScroll')
    hit.forceActiveFocus(Qt.TabFocusReason)
    for _ in range(10):
        QTest.keyClick(window,Qt.Key_Tab)
        QTest.qWait(20)
        focused=window.activeFocusItem()
        assert focused.objectName().startswith('manualTaskSearch-')
        top=focused.mapToItem(scroller,QPointF()).y()
        assert 0 <= top and top+focused.height() <= scroller.height()+1
    for _ in range(6):
        QTest.keyClick(window,Qt.Key_Backtab,Qt.ShiftModifier)
        QTest.qWait(20)
        focused=window.activeFocusItem()
        top=focused.mapToItem(scroller,QPointF()).y()
        assert 0 <= top and top+focused.height() <= scroller.height()+1
    expected=c.searchResults[4]
    QTest.keyClick(window,Qt.Key_Return)
    wait_until(lambda: c.chapterId == expected['chapterId'])
    wait_until(lambda: not find(window,'operationManual').property('restoring'))
    section=find(window,f'manualSection-{expected["sectionIndex"]}')
    reading=find(window,'manualReadingArea')
    assert 0 <= section.mapToItem(reading,QPointF()).y() < reading.height()
    assert not warnings, warnings


def test_task_home_at_large_interface_scale(tmp_path):
    # Interface scale is a startup-only Qt setting; a live preferences write
    # would not exercise scaled rendering in this already-running Qt process.
    import subprocess
    import sys
    env=dict(os.environ, QT_SCALE_FACTOR='1.3', QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
    env['MANUAL_TASK_EVIDENCE']=os.environ.get('MANUAL_TASK_EVIDENCE',str(tmp_path))
    result=subprocess.run([sys.executable,'-m','pytest',
        'tests/test_manual_tasks.py::test_task_home_live_language_and_narrow_controls[light-en-US-size1]',
        '-q','--tb=short'],env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
