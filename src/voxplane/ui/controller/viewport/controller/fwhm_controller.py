"""Independent wire-ramp ROI, analysis settings, jobs and per-slice results."""
from .mtf_controller import MtfController


class FwhmController(MtfController):
    TARGET_METHODS = ("ramp",)
