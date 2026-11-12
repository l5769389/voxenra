"""Offline operation manual and reading state owned by its workspace tab."""
from voxplane.i18n import message as _msg
from voxplane.i18n.messages import localize
from voxplane.i18n.qt import translated_property as _TextProperty
import json
import math
from voxplane.ui.manual_content import manual_content, manual_rich_text
from voxplane.core.manual_index import search_sections, chapter_neighbors, section_id

from PySide6.QtCore import Property, Signal, Slot

from voxplane.model import TabType
from voxplane.ui.controller.utility_tab_controller import UtilityTabController


class ManualTabController(UtilityTabController):
    _i18n_currentChapter = Signal()
    _i18n_navigation = Signal()
    _i18n_searchResults = Signal()
    _i18n_taskRoutes = Signal()

    chapterChanged = Signal()
    navigationChanged = Signal()
    navigationWidthChanged = Signal()

    def __init__(self, parent=None, *, settings=None):
        super().__init__(TabType.MANUAL, _msg('text.0495'), parent)
        self._content = manual_content()
        self._chapters = {c["id"]: c for c in self._content["chapters"]}
        self._chapter = "quick-start"
        self._show_tasks = False
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
        if self._show_tasks:
            return dict(title=_msg('manual.reader.tasks'), summary=_msg('manual.reader.routeHelp'),
                        categoryTitle='', icon='manual', sections=[], relatedChapters=[])
        chapter = dict(self._chapters[self._chapter])
        from voxplane.i18n import messages
        code = 'en' if messages._active is not None and messages._active.locale != 'zh-CN' else 'zh'
        # Animated examples now live next to their relevant instructions.
        if chapter.get('example', '').endswith('.gif'):
            chapter.pop('example')
        if code == 'en':
            if chapter.get('example'): chapter['example'] = 'en/' + chapter['example']
            if chapter.get('examples'): chapter['examples'] = ['en/' + name for name in chapter['examples']]
        category = next(c for c in self._content["categories"] if c["id"] == chapter["category"])
        previous, following = chapter_neighbors(self._content['chapters'], self._chapter)
        def neighbor(key):
            return dict(id=key, title=self._chapters[key]['title']) if key else {}
        return dict(chapter, categoryTitle=category["title"], previous=neighbor(previous), next=neighbor(following),
                    sections=[dict(section, sectionId=section_id(section, index), bodyHtml=manual_rich_text(section["body"]),
                                   tutorials=[dict(id=item['name'], file=item['sources'][code],
                                                   poster=item['posters'][code],
                                                   caption=_msg('manual.tutorial.' + item['name'] + '.caption'))
                                              for item in section.get('tutorials', [])])
                              for index, section in enumerate(chapter["sections"])],
                    relatedChapters=[dict(id=key, title=_msg("manual." + key + ".title"))
                                     for key in chapter.get("related", [])
                                     if key in self._chapters or key in self._aliases])

    @Property(bool, notify=chapterChanged)
    def showTasks(self):
        return self._show_tasks

    @Slot()
    def selectTasks(self):
        self._show_tasks = True
        self._section_index = -1
        self.chapterChanged.emit()

    @_TextProperty('QVariantList', notify=_i18n_taskRoutes, notify_name='_i18n_taskRoutes', source_notify='chapterChanged')
    def taskRoutes(self):
        return [dict(id=route['id'], title=_msg('manual.route.' + route['id'] + '.title'),
                     summary=_msg('manual.route.' + route['id'] + '.summary'),
                     chapters=[dict(id=key, title=self._chapters[key]['title']) for key in route['chapters']])
                for route in self._content.get('routes', [])]

    @_TextProperty('QVariantList', notify=_i18n_searchResults, notify_name='_i18n_searchResults', source_notify='navigationChanged')
    def searchResults(self):
        return search_sections(localize(self._content['chapters']), self._search, limit=31)

    @Slot(str, int)
    def selectSection(self, chapter_id, index):
        chapter = self._chapters.get(chapter_id)
        if chapter is None or not 0 <= index < len(chapter['sections']):
            return
        self._show_tasks = False
        self._chapter = chapter_id
        self._section_index = index
        self._positions[chapter_id] = 0.0
        self._expanded.add(chapter['category'])
        self.navigationChanged.emit()
        self.chapterChanged.emit()

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
        self._show_tasks = False
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
        return 0.0 if self._show_tasks else self._positions.get(self._chapter, 0.0)

    @Slot(float)
    def setScrollPosition(self, value):
        if not self._show_tasks and math.isfinite(value):
            self._positions[self._chapter] = max(0.0, value)
            self._section_index = -1
