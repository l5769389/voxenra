"""Independent toolbar drafts merge only the ordering fields they changed."""
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app


def test_dirty_right_draft_preserves_another_editors_saved_left_order(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    left = settings.createToolbarEditor(settings)
    right = settings.createToolbarEditor(settings)
    clean = settings.createToolbarEditor(settings)
    assert left.moveLeftView(2, 0)
    assert right.moveTool('common', 1, 0)
    assert left.save()
    assert clean.leftViews[0]['toolType'] == '3d'
    assert not clean.dirty
    # A notification must not replace a pending draft in another editor.
    assert right.commonTools[0]['toolType'] == 'scroll' and right.dirty
    assert right.save()
    restored = SettingsController(path=settings._path)
    assert restored.navigationViewOrder[:3] == ['3d', '2d', 'mpr']
    assert restored.section('toolbar')['rightProfiles']['2d:ct']['common'][0] == 'scroll'
    assert clean.commonTools[0]['toolType'] == 'scroll' and not clean.dirty


def test_independent_profile_edits_and_profile_reset_merge(qt_app):
    settings = SettingsController(path=False)
    settings.setValue('toolbar', 'rightProfiles', {
        '2d:ct': {'common': ['zoom', 'window'], 'more': ['export']}})
    resetting = settings.createToolbarEditor(settings)
    mr = settings.createToolbarEditor(settings)
    resetting.restoreCurrentDefault()
    mr.selectProfile('mpr:mr')
    mr.moveTool('common', 2, 0)
    assert mr.save()
    assert resetting.save()
    profiles = settings.section('toolbar')['rightProfiles']
    assert '2d:ct' not in profiles
    assert profiles['mpr:mr']['common'][:3] == ['pan', 'window', 'scroll']
    assert mr.commonTools[0]['toolType'] == 'pan' and not mr.dirty


def test_same_profile_last_save_wins_as_one_valid_group_pair(qt_app):
    settings = SettingsController(path=False)
    first = settings.createToolbarEditor(settings)
    second = settings.createToolbarEditor(settings)
    first.moveTool('common', 1, 0)
    second.moveToGroup('play', 'more')
    second.moveToGroup('export', 'common')
    assert first.save()
    assert second.save()
    profile = settings.section('toolbar')['rightProfiles']['2d:ct']
    assert profile['common'] == ['window','scroll','pan','zoom','measure','mpr-layout','export']
    assert 'play' in profile['more'] and 'export' not in profile['more']
    assert first.commonTools[-1]['toolType'] == 'export' and not first.dirty
