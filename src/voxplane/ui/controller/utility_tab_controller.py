from PySide6.QtCore import QObject, Property

from voxplane.model import TabConfig, TabType


class UtilityTabController(QObject):
    """A workspace page without image viewports or image tools."""

    def __init__(self, tab_type: TabType, label: str, parent=None):
        super().__init__(parent)
        self.tab_config = TabConfig(f"workspace-{tab_type.value}", label, tab_type, ())
        self.viewports_by_id = {}

    @Property(QObject, constant=True)
    def activeViewport(self):
        return None

    @Property(QObject, constant=True)
    def toolController(self):
        return None

    def pausePlayback(self):
        pass

    def dispose(self):
        pass

    def contains_viewport(self, viewport_id):
        return False
