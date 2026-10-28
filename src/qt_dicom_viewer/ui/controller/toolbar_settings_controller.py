"""Transactional toolbar editor; rendered previews share the runtime resolver."""
from copy import deepcopy

from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as TextProperty
from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.settings.toolbar import LEFT_VIEWS, navigation_order, resolved_groups

VIEW_LABELS = dict(zip(LEFT_VIEWS, ('text.0679', 'text.0680', 'text.0681', 'text.0682', 'text.0683', 'text.0684', 'text.0685')))
VIEW_ICONS = dict(zip(LEFT_VIEWS, ('nav-view-2d','nav-view-mpr','nav-view-3d','nav-view-tile','nav-view-4d','nav-view-tag','fusion')))
PROFILE_MODES = {
    '2d': ('ct','mr','pt','other','color'), 'mpr': ('ct','mr','pt'),
    '3d': ('ct','mr','pt','petct3d'), 'montage': ('ct','mr','other'),
    '4d': ('ct','mr'), 'compare2d': ('ct','mr','pt','other','color'),
    'comparempr': ('ct','mr','pt'), 'petctfusion': ('pt',),
}


class ToolbarSettingsController(QObject):
    changed = Signal()
    _i18n_profiles = Signal()
    _i18n_leftViews = Signal()
    _i18n_commonTools = Signal()
    _i18n_moreTools = Signal()
    _i18n_message = Signal()

    def __init__(self, settings, owner):
        super().__init__(owner)
        self._settings = settings
        self._profile = '2d:ct'
        self._scope = 'right'
        self._message = ''
        self._draft = settings.section('toolbar')
        self._baseline = deepcopy(self._draft)
        settings.sectionChanged.connect(self._settings_changed)

    @Slot(str)
    def _settings_changed(self, section):
        if section == 'toolbar' and not self.dirty:
            self.beginEdit()

    @Property(str, notify=changed)
    def scope(self):
        return self._scope

    @Slot(str)
    def selectScope(self, value):
        if value in ('left', 'right'):
            self._scope = value
            self.changed.emit()

    @Property(str, notify=changed)
    def selectedProfile(self):
        return self._profile

    @Slot(str)
    def selectProfile(self, value):
        if value in [p['key'] for p in self.profiles]:
            self._profile = value
            self._message = ''
            self.changed.emit()

    @TextProperty('QVariantList', notify=_i18n_profiles, notify_name='_i18n_profiles')
    def profiles(self):
        mode_labels = {**{key: _msg(value) for key, value in VIEW_LABELS.items()},
                       'compare2d': _msg('compare.title'), 'comparempr': _msg('compare.mpr.title'),
                       'petctfusion': _msg('text.0685')}
        labels = {'other': _msg('toolbar.scalar'), 'color': _msg('toolbar.color'), 'petct3d': 'PET/CT'}
        return [dict(key=f'{mode}:{capability}', label=mode_labels[mode] + ' · ' + labels.get(capability, capability.upper()))
                for mode, capabilities in PROFILE_MODES.items() for capability in capabilities]

    @Property(bool, notify=changed)
    def dirty(self):
        return self._draft != self._baseline

    @TextProperty(str, notify=_i18n_message, notify_name='_i18n_message', source_notify='changed')
    def message(self):
        return _msg(self._message) if self._message else ''

    @TextProperty('QVariantList', notify=_i18n_leftViews, notify_name='_i18n_leftViews', source_notify='changed')
    def leftViews(self):
        return [dict(toolType=key, label=_msg(VIEW_LABELS[key]), iconName=VIEW_ICONS[key], available=True)
                for key in navigation_order(self._draft['leftViews'])]

    def _tools(self):
        # Import lazily: ToolController itself uses SettingsController.
        from .tab.tool_controller import build_tool_items
        mode, capability = self._profile.split(':')
        return build_tool_items(TabType(mode), capability.upper(), supports_ct_analysis=True,
                                is_color=capability == 'color', color_calibrated=True)

    def _groups(self):
        if self._profile in self._draft['rightProfiles']:
            saved = deepcopy(self._draft['rightProfiles'][self._profile])
            saved['more'] += [t['toolType'] for t in self._tools()
                              if t['toolType'] not in saved['common'] + saved['more']]
            return saved
        mode, capability = self._profile.split(':')
        groups = resolved_groups(TabType(mode), capability.upper(), capability == 'color', self._tools(), {})
        return dict(common=groups['common'] + groups['primary'], more=groups['more'])

    def _items(self, group):
        tools = {t['toolType']: t for t in self._tools()}
        return [tools.get(key, dict(toolType=key, label=key, iconName='more', available=False))
                for key in self._groups()[group]]

    @TextProperty('QVariantList', notify=_i18n_commonTools, notify_name='_i18n_commonTools', source_notify='changed')
    def commonTools(self):
        return self._items('common')

    @TextProperty('QVariantList', notify=_i18n_moreTools, notify_name='_i18n_moreTools', source_notify='changed')
    def moreTools(self):
        return self._items('more')

    @Slot()
    def beginEdit(self):
        self._draft = self._settings.section('toolbar')
        self._baseline = deepcopy(self._draft)
        self._message = ''
        self.changed.emit()

    @Slot()
    def cancel(self):
        self.beginEdit()

    @Slot(result=bool)
    def save(self):
        if not self._settings.save_toolbar_preferences(self._draft, self._baseline):
            return False
        self.beginEdit()
        return True

    @Slot()
    def restoreCurrentDefault(self):
        if self._scope == 'left':
            self._draft['leftViews'] = []
        else:
            self._draft['rightProfiles'].pop(self._profile, None)
        self._message = ''
        self.changed.emit()

    @Slot(int, int, result=bool)
    def moveLeftView(self, source, destination):
        entries = navigation_order(self._draft['leftViews'])
        if not 0 <= source < len(entries) or not 0 <= destination < len(entries):
            return False
        entries.insert(destination, entries.pop(source))
        self._draft['leftViews'] = entries
        self.changed.emit()
        return True

    @Slot(str, int, int, result=bool)
    def moveTool(self, group, source, destination):
        if group not in ('common', 'more'):
            return False
        groups = self._groups()
        entries = groups[group]
        if not 0 <= source < len(entries) or not 0 <= destination < len(entries):
            return False
        entries.insert(destination, entries.pop(source))
        self._draft['rightProfiles'][self._profile] = groups
        self._message = ''
        self.changed.emit()
        return True

    @Slot(str, str, result=bool)
    def moveToGroup(self, key, destination):
        if destination not in ('common', 'more'):
            return False
        groups = self._groups()
        source = 'more' if destination == 'common' else 'common'
        if key not in groups[source]:
            return False
        if destination == 'common' and len(groups['common']) >= 7:
            self._message = 'toolbar.limit'
            self.changed.emit()
            return False
        groups[source].remove(key)
        groups[destination].append(key)
        self._draft['rightProfiles'][self._profile] = groups
        self._message = ''
        self.changed.emit()
        return True
