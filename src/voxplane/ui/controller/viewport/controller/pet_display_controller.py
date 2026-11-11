"""PET display intent and committed state, shared by every PET layer in a tab."""
from dataclasses import dataclass, replace
from math import floor, isfinite, log10

from PySide6.QtCore import QObject, Signal

from voxplane.model import PixelValueMeta, WindowLevel


@dataclass(frozen=True)
class PetDisplayState:
    meta: PixelValueMeta
    upper: float
    control: float
    presets: tuple[float, ...]

    @property
    def window(self):
        return WindowLevel(self.upper / 2, self.upper)

    @property
    def minimum(self):
        return 0.01 if self.meta.is_suv else 0.001


class PetDisplayController(QObject):
    changed = Signal()
    invalidated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.applied: PetDisplayState | None = None
        self.target: PetDisplayState | None = None
        self.baseline: PetDisplayState | None = None
        self.color_map = "grayscale"

    @property
    def visible(self):
        if self.applied and self.target and self.applied.meta.unit_id == self.target.meta.unit_id:
            return self.target
        return self.applied

    @property
    def pending(self):
        return bool(self.applied and self.target and
                    self.applied.meta.unit_id != self.target.meta.unit_id)

    def accept(self, meta, window):
        upper = max(window.center + window.width / 2, 0.01 if meta.is_suv else 0.001)
        state = self.target
        if state is None or state.meta.unit_id != meta.unit_id:
            magnitude = 10 ** floor(log10(max(upper, 0.001)))
            presets = ((5., 10., 20., 30., 40.) if meta.is_suv else
                       tuple(x * magnitude for x in (0.5, 1, 2, 3, 4, 5, 10)))
            control = max(30., upper) if meta.is_suv else next(x for x in presets if x >= upper)
            state = PetDisplayState(meta, upper, control, presets)
        else:
            # Keep the initialization reference factors for display thresholds,
            # but use the current frame's availability and quantitative warning.
            options = tuple(replace(o, available=next((n.available for n in meta.unit_options
                                                      if n.unit_id == o.unit_id), False),
                                    warning=next((n.warning for n in meta.unit_options
                                                  if n.unit_id == o.unit_id), o.warning))
                            for o in state.meta.unit_options)
            state = replace(state, upper=upper, control=max(state.control, upper),
                            meta=replace(state.meta, warning=meta.warning, unit_options=options))
        self.applied = self.target = state
        if self.baseline is None:
            self.baseline = state
        self.changed.emit()

    def fail(self):
        self.target = self.applied
        self.changed.emit()

    def _set(self, state):
        if state == self.target:
            self.changed.emit()  # restore clamped text fields, even on a no-op
            return
        self.target = state
        self.changed.emit()
        self.invalidated.emit()

    def set_upper(self, value):
        if self.target is None or not isfinite(value):
            return
        self._set(replace(self.target, upper=min(max(value, self.target.minimum), self.target.control)))

    def set_control(self, value):
        if self.target is None or not isfinite(value) or value <= 0:
            return
        control = max(value, self.target.minimum)
        self._set(replace(self.target, control=control, upper=min(self.target.upper, control)))

    def set_unit(self, unit_id):
        state = self.target
        if state is None or state.meta.unit_id == unit_id:
            return
        option = next((o for o in state.meta.unit_options if o.unit_id == unit_id and o.available), None)
        if option is None:
            return
        ratio = option.scale_from_source / state.meta.scale_from_source
        meta = replace(state.meta, unit=option.unit, unit_id=option.unit_id,
                       scale_from_source=option.scale_from_source,
                       suv_type="BW" if unit_id == "suvbw" else None)
        minimum = 0.01 if meta.is_suv else 0.001
        self._set(PetDisplayState(meta, max(minimum, state.upper * ratio),
                                 max(minimum, state.control * ratio),
                                 tuple(p * ratio for p in state.presets)))

    def reset(self):
        if self.baseline is None or self.target is None:
            return
        available = {o.unit_id for o in self.target.meta.unit_options if o.available}
        if self.baseline.meta.unit_id not in available and available:
            return
        self._set(self.baseline)
