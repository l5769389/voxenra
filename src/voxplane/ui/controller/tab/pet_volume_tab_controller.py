from uuid import uuid4
from voxplane.model import ViewportConfig
from voxplane.model.dicom_models import VolumeViewType
from voxplane.ui.controller.viewport.pet_volume_viewport_controller import PetVolumeViewportController
from .tab_controller import TabController


class PetVolumeTabController(TabController):
    def __init__(self, config, source, parent=None):
        self.source_workspace = source
        super().__init__(config, parent)
        # The viewport owns the live subscription and releases it on source
        # close; do not retain the entire four-pane workspace a second time.
        self.source_workspace = None
        self._tool_controller.activateTool("volume-preset")

    def _create_tool_controller(self):
        super()._create_tool_controller()
        self._tool_controller._modality = "PETCT3D"

    def _create_viewport_dict(self):
        meta = self._tab_config.series_metas[0]
        config = ViewportConfig(str(uuid4()), self._tab_config.tab_id, VolumeViewType.VOLUME,
                                meta.series_uid, meta, "fusion-volume")
        view = PetVolumeViewportController(config, self._tool_controller, self.source_workspace, self)
        self._viewport_dict[config.viewport_id] = view
        self._active_viewport_id = config.viewport_id

    def init_render(self):
        self.activeViewport.request_render()
