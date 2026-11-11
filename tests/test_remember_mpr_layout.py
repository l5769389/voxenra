"""Layout preferences affect future tabs, not restored or already-open tabs."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QObject

from voxplane.model import TabConfig, TabType
from voxplane.settings.preferences import normalize_settings
from voxplane.ui.controller.settings_controller import SettingsController
from voxplane.ui.controller.tab.tab_controller import TabController
from test_four_d import _four_d_meta
from test_measurement_qml import qt_app


@pytest.fixture
def tabs(qt_app, tmp_path):
    path = tmp_path / 'display.json'
    owners, created = [], []

    def create(kind=TabType.MPR, modality='CT', restart=False):
        if not owners or restart:
            owner = QObject()
            owner._settings_controller = SettingsController(owner, path=path)
            owners.append(owner)
        tab = TabController(TabConfig(str(len(created)), 'layout', kind,
            (replace(_four_d_meta(), modality=modality),)), owners[-1])
        created.append(tab)
        return tab.mprLayout

    yield create, path, owners
    for layout in created:
        layout.dispose()


def test_remember_auto_updates_survives_restart_and_can_be_disabled(tabs):
    create, path, owners = tabs
    first = create()
    existing = create()
    assert first.layout == 'right' and not first.rememberLayout
    first.setLayout('columns')
    assert create().layout == 'right'
    first.setRememberLayout(True)
    assert first.rememberLayout and existing.rememberLayout
    assert existing.layout == 'right'
    assert create(modality='MR').layout == 'columns'
    first.setLayout('quad')
    assert existing.layout == 'right'
    restarted = create(restart=True)
    assert restarted.layout == 'quad' and restarted.rememberLayout
    restarted.setRememberLayout(False)
    assert restarted.layout == 'quad' and not restarted.rememberLayout
    restarted.setLayout('rows')
    assert create(restart=True).layout == 'right'


def test_mpr_and_four_d_preferences_do_not_overwrite_each_other(tabs):
    create, _, _ = tabs
    mpr, temporal = create(), create(TabType.FOUR_D)
    mpr.setLayout('columns')
    mpr.setRememberLayout(True)
    temporal.setLayout('quad')
    temporal.setRememberLayout(True)
    assert create().layout == 'columns'
    assert create(TabType.FOUR_D).layout == 'quad'
    temporal.setRememberLayout(False)
    assert create(TabType.FOUR_D, restart=True).layout == 'right'
    assert create().layout == 'columns'


def test_workspace_restore_overrides_preference_without_saving_over_it(tabs):
    create, _, owners = tabs
    layout = create()
    layout.setLayout('quad')
    layout.setRememberLayout(True)
    restored = create()
    restored.restore({'layout': 'left'})
    assert restored.layout == 'left'
    assert create().layout == 'quad'
    # An explicit click on even the already-selected layout updates the preference.
    restored.setLayout('left')
    assert create().layout == 'left'
    restored.restore({})
    assert restored.layout == 'right'
    assert create().layout == 'left'


def test_invalid_preferences_fall_back_and_failed_write_is_not_remembered(tabs, tmp_path):
    create, _, owners = tabs
    for value in ('missing', None, {}, [], 3, True):
        assert normalize_settings({'layout': {'rememberedMprLayout': value}})['layout']['rememberedMprLayout'] == ''
    layout = create()
    layout.setLayout('quad')
    settings = owners[-1]._settings_controller
    settings._path = tmp_path  # Cannot atomically replace a directory with JSON.
    layout.setRememberLayout(True)
    assert not layout.rememberLayout and layout.preferenceError
    assert layout.layout == 'quad'
    assert create().layout == 'right'
