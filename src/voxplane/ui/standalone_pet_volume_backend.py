"""PET transfer functions on the regular single-volume GPU/crop pipeline."""
from .volume_render_backend import VolumeRenderBackend
from .pet_volume_render_backend import pet_transfer_functions


class StandalonePetVolumeBackend(VolumeRenderBackend):
    use_index_grid = False

    def __init__(self, widget, controller):
        super().__init__(widget)
        self.controller = controller

    def apply_display(self, state):
        if self.volume is None:
            return
        c = self.controller
        key = (c.petUpper, c.petThreshold, c.petPalette, c.petOpacity)
        if key == self._applied_display:
            return
        colors, opacity = pet_transfer_functions(*key[:2], key[2], key[3])
        self.mapper.SetBlendModeToComposite()
        self.properties.SetColor(colors)
        self.properties.SetScalarOpacity(opacity)
        self.properties.ShadeOff()
        g = self.volume.geometry
        self.properties.SetScalarOpacityUnitDistance(min(g.column_spacing, g.row_spacing, g.slice_spacing))
        self._applied_display = key

    def dispose(self):
        super().dispose()
        self.controller = None
