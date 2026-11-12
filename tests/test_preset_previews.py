import base64
from PySide6.QtGui import QImage
from test_dicom_tags import qt_app, wait_until
from voxplane.ui.controller.settings_controller import SettingsController
from voxplane.ui.controller.preset_preview_controller import PresetPreviewController


def decoded(url):
    return QImage.fromData(base64.b64decode(url.split(',',1)[1]))


def test_display_preview_changes_window_and_zoom_without_touching_defaults(qt_app):
    settings=SettingsController(path=False)
    preview=PresetPreviewController(settings,'initialDisplay')
    preview.refresh(); first=preview.pages[0]
    settings.setValue('initialDisplay','zoom','pixel')
    wait_until(lambda: preview.pages[0]!=first)
    pixel=preview.pages[0]
    settings.setValue('initialDisplay','windowMode','preset')
    settings.setValue('initialDisplay','ctPreset','ct-lung')
    wait_until(lambda: preview.pages[0]!=pixel)
    assert not preview.error
    before=settings.values
    preview.setModality('MR'); wait_until(lambda: preview.caption.startswith('MR'))
    assert settings.values==before
    settings.deleteLater()


def test_screenshot_preview_layers_scope_and_size(qt_app):
    settings=SettingsController(path=False)
    preview=PresetPreviewController(settings,'screenshot');preview.refresh()
    first=preview.pages[0]
    settings.setExportOptions('screenshot',{'measurements':False})
    wait_until(lambda: preview.pages[0]!=first)
    clean=preview.pages[0]
    settings.setExportOptions('screenshot',{'scope':'tab','anonymous':False,'format':'jpeg','size':'longEdge','longEdge':2048})
    wait_until(lambda: preview.pages[0]!=clean)
    assert preview.pages[0].startswith('data:image/jpeg;')
    assert '2048 × 1229' in preview.caption
    assert not decoded(preview.pages[0]).isNull()
    settings.deleteLater()


def test_report_preview_uses_pdf_pages_and_updates_layout(qt_app):
    settings=SettingsController(path=False)
    preview=PresetPreviewController(settings,'report');preview.refresh()
    assert preview.pages and not preview.error
    first=decoded(preview.pages[0]); assert first.height()>first.width()
    original=preview.pages[0]
    settings.setExportOptions('report',{'orientation':'landscape','organization':'Example Hospital','tableDetail':'detailed','fontSize':'large','imageColumns':2})
    wait_until(lambda: preview.pages[0]!=original)
    image=decoded(preview.pages[0]);assert image.width()>image.height()
    assert not preview.error
    settings.deleteLater()


def test_report_details_and_image_options_have_visible_effect(qt_app):
    settings=SettingsController(path=False)
    preview=PresetPreviewController(settings,'report');preview.refresh()
    original=preview.pages[:]
    settings.setExportOptions('report',{'tableDetail':'detailed'})
    wait_until(lambda: preview.pages!=original)
    assert not preview.error
    illustrated_count=len(preview.pages)
    settings.setExportOptions('report',{'includeImages':False})
    wait_until(lambda: len(preview.pages)<illustrated_count)
    settings.deleteLater()


def test_export_reset_refreshes_both_examples(qt_app):
    settings=SettingsController(path=False)
    screenshot=PresetPreviewController(settings,'screenshot');screenshot.refresh()
    report=PresetPreviewController(settings,'report');report.refresh()
    originals=(screenshot.pages[:],report.pages[:])
    settings.setExportOptions('screenshot',{'scope':'tab'})
    settings.setExportOptions('report',{'orientation':'landscape'})
    wait_until(lambda:screenshot.pages!=originals[0] and report.pages!=originals[1])
    settings.resetSection('export')
    wait_until(lambda:screenshot.pages==originals[0] and report.pages==originals[1])
    settings.deleteLater()


def test_preview_sources_have_enough_pixels_for_large_display(qt_app):
    settings=SettingsController(path=False)
    image=PresetPreviewController(settings,'screenshot');image.refresh()
    assert decoded(image.pages[0]).size().width() >= 1200
    report=PresetPreviewController(settings,'report');report.refresh()
    assert decoded(report.pages[0]).size().width() >= 1700
    settings.deleteLater()


def test_example_fields_follow_viewport_order_privacy_and_modality(qt_app):
    from copy import deepcopy
    from voxplane.settings.preferences import DEFAULTS
    from voxplane.ui.controller.preset_preview_controller import example_corner_rows
    corners=deepcopy(DEFAULTS['corners'])
    rows=example_corner_rows('CT',(350,40),corners)
    assert rows['topLeft'][-1]=='Slice: 26 / 100'
    assert rows['topRight']==['Patient: DEMO','ID: DEMO-001','Study date: 2026/01/01']
    assert 'WW: 350   WL: 40' in rows['bottomLeft']
    assert example_corner_rows('CT',(350,40),corners,hide_identity=True)['topRight']==[]
    mr=example_corner_rows('MR',(800,400),corners)
    assert any('TR:' in row for row in mr['bottomLeft'])
    assert not any('HU' in row or 'kV:' in row for group in mr.values() for row in group)
    corners['topRight']=['window','slice']
    assert example_corner_rows('CT',(80,40),corners)['topRight']==['WW: 80   WL: 40','Slice: 26 / 100']


def test_demo_geometry_and_corner_visibility_match_export(qt_app):
    from voxplane.ui.controller.preset_preview_controller import example_geometry,example_image
    for zoom in ['fit','pixel']:
        g=example_geometry(zoom)
        assert g['roiDiameter']/g['scaleLength']==.5
        assert abs(g['lineLength']/g['scaleLength']-38.4/50)<1e-8
    anonymous=example_image(layers={'anonymous':True})
    no_parameters=example_image(layers={'parameters':False})
    assert anonymous==no_parameters
    assert example_image()!=anonymous


def test_display_preview_refreshes_corner_and_privacy_changes(qt_app):
    settings=SettingsController(path=False)
    preview=PresetPreviewController(settings,'initialDisplay');preview.refresh()
    first=preview.pages[0]
    settings.setValue('privacy','hideIdentity',True)
    wait_until(lambda: preview.pages[0]!=first)
    private=preview.pages[0]
    settings.setValue('corners','enabled',False)
    wait_until(lambda: preview.pages[0]!=private)
    settings.deleteLater()
