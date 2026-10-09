"""Stable, capability-aware priorities for the active view (not catalog order)."""
import pytest
from test_dicom_tags import qt_app
from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import build_tool_items
from qt_dicom_viewer.model.toolbar_priorities import toolbar_groups

@pytest.mark.parametrize('kind,modality,common,primary', [
    (TabType.TWO_D, 'CT', ['window','scroll','pan','zoom'], ['measure','mpr-layout','play']),
    (TabType.MPR, 'MR', ['window','scroll','pan','zoom'], ['measure','segmentation','mip']),
    (TabType.FOUR_D, 'CT', ['window','play','pan','zoom'], ['measure','segmentation','mip']),
    (TabType.TWO_D, 'PT', ['window','scroll','pan','zoom'], ['pseudocolor','measure','mpr-layout']),
    (TabType.MPR, 'PT', ['window','scroll','pan','zoom'], ['pseudocolor','measure','segmentation']),
    (TabType.PETCT_FUSION, 'PT', ['ct-window','pet-window','pan','zoom'], ['pseudocolor','fusion-blend','measure']),
    (TabType.THREE_D, 'CT', ['volume-rotate','pan','zoom','window'], ['volume-preset','volume-direction','volume-crop']),
    (TabType.THREE_D, 'PT', ['volume-rotate','pan','zoom'], ['volume-preset','volume-direction','volume-crop']),
    (TabType.MONTAGE, 'MR', ['window','pan','zoom'], ['rotate','pseudocolor']),
])
def test_context_priorities(kind, modality, common, primary):
    tools = build_tool_items(kind, modality)
    for items in (tools, list(reversed(tools))):
        groups = toolbar_groups(kind, modality, False, items)
        assert groups == {'common':common, 'primary':primary}
        assert len(set(common+primary)) == len(common+primary)
        assert set(common+primary) <= {t['toolType'] for t in tools}


def test_color_and_reference_view():
    tools = build_tool_items(TabType.TWO_D,'OT',is_color=True)
    assert toolbar_groups(TabType.TWO_D,'OT',True,tools) == {
        'common':['scroll','pan','zoom','rotate'], 'primary':['annotate','mpr-layout']}
    tools = build_tool_items(TabType.THREE_D,'CT') + [{'toolType':'play'}, {'toolType':'mpr-layout'}]
    assert toolbar_groups(TabType.THREE_D,'CT',False,tools)['common'] == ['volume-rotate','pan','zoom','play']


def test_controller_updates_profile_for_active_series(qt_app):
    from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
    from qt_dicom_viewer.model import SeriesDisplayMeta
    controller = ToolController(tab_type=TabType.TWO_D,modality='CT')
    assert 'pseudocolor' not in controller.toolbarGroups['primary']
    controller.set_series_capabilities(SeriesDisplayMeta(patient_name='',patient_id='',study_description='',series_description='',series_uid='pet',modality='PT'))
    assert controller.toolbarGroups['primary'][0] == 'pseudocolor'


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_profiles_render_and_switch_in_place(qt_app, tmp_path, locale):
    from pathlib import Path
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    from shiboken6 import delete
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
    from test_measurement_qml import _visual_children
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    from qt_dicom_viewer.ui.controller.language_controller import LanguageController
    language = LanguageController(SettingsController(path=False), root=False)
    language.selectLanguage(locale)
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    controllers = [ToolController(tab_type=kind,modality=modality) for kind,modality in [
        (TabType.TWO_D,'CT'), (TabType.TWO_D,'PT'), (TabType.MPR,'MR'),
        (TabType.FOUR_D,'CT'), (TabType.PETCT_FUSION,'PT'), (TabType.THREE_D,'CT')]]
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setInitialProperties({'toolController':controllers[0]})
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/right/PrimaryToolBar.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    try:
        for index,controller in enumerate(controllers):
            view.rootObject().setProperty('toolController',controller)
            for width in (240,300):
                view.resize(width,100)
                QTest.qWait(45)
                buttons = [i for i in _visual_children(view.rootObject())
                           if i.isVisible() and i.objectName().startswith('primaryTool-')]
                expected = controller.toolbarGroups['common']+controller.toolbarGroups['primary']
                assert [i.objectName().removeprefix('primaryTool-') for i in buttons] == expected
                assert view.rootObject().property('implicitHeight') <= 110
                assert all(i.width()>0 and i.height()>0 for i in buttons)
                labels = [i for i in _visual_children(view.rootObject())
                          if i.isVisible() and i.objectName() == 'toolbarLabel']
                assert not labels  # All toolbar captions are hover-only.
                assert view.grabWindow().save(str(tmp_path/f'profile-{index}-{width}.png'))
        assert not warnings,warnings
    finally:
        view.close()
        delete(view)
        language.shutdown()
