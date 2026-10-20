"""Offline operation manual and reading state owned by its workspace tab."""
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import localize
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
import json
import math
from qt_dicom_viewer.ui.manual_content import manual_content, manual_rich_text

from PySide6.QtCore import Property, Signal, Slot

from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.controller.utility_tab_controller import UtilityTabController


class ManualTabController(UtilityTabController):
    _i18n_currentChapter = Signal()
    _i18n_navigation = Signal()

    chapterChanged = Signal()
    navigationChanged = Signal()
    navigationWidthChanged = Signal()

    def __init__(self, parent=None, *, settings=None):
        super().__init__(TabType.MANUAL, _msg('text.0495'), parent)
        self._content = manual_content()
        self._chapters = {c["id"]: c for c in self._content["chapters"]}
        self._chapter = "quick-start"
        self._search = ""
        self._positions = {}
        self._aliases = self._content.get("aliases", {})
        self._expanded = {"start"}
        self._section_index = -1
        self._settings = settings
        self._navigation_width = 260
        if settings is not None:
            settings.sectionChanged.connect(self._settings_changed)

    @Slot(str)
    def _settings_changed(self, section):
        if section == "layout": self.navigationWidthChanged.emit()

    @Property(int, notify=navigationWidthChanged)
    def navigationWidth(self):
        return (self._settings.section("layout")["manualNavigationWidth"]
                if self._settings is not None else self._navigation_width)

    @Slot(int)
    def setNavigationWidth(self, width):
        width = max(220, min(400, width))
        if self._settings is not None:
            self._settings.setValue("layout", "manualNavigationWidth", width)
        elif self._navigation_width != width:
            self._navigation_width = width
            self.navigationWidthChanged.emit()

    @Property(int, notify=chapterChanged)
    def sectionIndex(self):
        return self._section_index

    @Slot(str)
    def toggleCategory(self, category):
        if category not in {c['id'] for c in self._content['categories']}: return
        if category in self._expanded: self._expanded.remove(category)
        else: self._expanded.add(category)
        self.navigationChanged.emit()

    @Property(str, notify=chapterChanged)
    def chapterId(self):
        return self._chapter

    @_TextProperty('QVariantMap', notify=_i18n_currentChapter, notify_name='_i18n_currentChapter', source_notify='chapterChanged')
    def currentChapter(self):
        chapter = dict(self._chapters[self._chapter])
        from qt_dicom_viewer.i18n import messages
        code = 'en' if messages._active is not None and messages._active.locale != 'zh-CN' else 'zh'
        # Animated examples now live next to their relevant instructions.
        if chapter.get('example', '').endswith('.gif'):
            chapter.pop('example')
        if code == 'en':
            if chapter.get('example'): chapter['example'] = 'en/' + chapter['example']
            if chapter.get('examples'): chapter['examples'] = ['en/' + name for name in chapter['examples']]
        category = next(c for c in self._content["categories"] if c["id"] == chapter["category"])
        return dict(chapter, categoryTitle=category["title"],
                    sections=[dict(section, bodyHtml=manual_rich_text(section["body"]),
                                   tutorials=[dict(id=item['name'], file=item['sources'][code],
                                                   poster=item['posters'][code],
                                                   caption=_msg('manual.tutorial.' + item['name'] + '.caption'))
                                              for item in section.get('tutorials', [])])
                              for section in chapter["sections"]],
                    relatedChapters=[dict(id=key, title=_msg("manual." + key + ".title"))
                                     for key in chapter.get("related", [])
                                     if key in self._chapters or key in self._aliases])

    @Property(str, notify=navigationChanged)
    def search(self):
        return self._search

    @Slot(str)
    def setSearch(self, value):
        if self._search != value:
            self._search = value
            self.navigationChanged.emit()

    @_TextProperty('QVariantList', notify=_i18n_navigation, notify_name='_i18n_navigation', source_notify='navigationChanged')
    def navigation(self):
        query = self._search.strip().casefold()
        rows = []
        for category in self._content["categories"]:
            chapters = [c for c in self._content["chapters"] if c["category"] == category["id"]
                        and (not query or query in json.dumps(localize(c), ensure_ascii=False).casefold()
                             or query in localize(category["title"]).casefold())]
            if chapters:
                rows.append(dict(category, expanded=bool(query) or category["id"] in self._expanded,
                                 chapters=[dict(id=c["id"], title=c["title"], icon=c["icon"]) for c in chapters]))
        return rows

    @Slot(str)
    def selectChapter(self, chapter_id):
        alias = self._aliases.get(chapter_id)
        self._section_index = alias["section"] if alias else -1
        if alias: chapter_id = alias["chapter"]
        if chapter_id not in self._chapters:
            chapter_id = "quick-start"
        self._chapter = chapter_id
        self._positions[chapter_id] = 0.0
        category = self._chapters[chapter_id]["category"]
        self._expanded.add(category)
        self.navigationChanged.emit()
        self.chapterChanged.emit()

    @Property(float, notify=chapterChanged)
    def scrollPosition(self):
        return self._positions.get(self._chapter, 0.0)

    @Slot(float)
    def setScrollPosition(self, value):
        if math.isfinite(value):
            self._positions[self._chapter] = max(0.0, value)
            self._section_index = -1
