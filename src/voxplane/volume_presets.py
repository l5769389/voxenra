"""Built-in display presets. A future file loader can supply the same data types.

Bone/vessel RGB anchors are sampled from XiaoSaiViewer 2.6.2's readable CLUTs;
bone/lung windows reference its WLWW.xml. Opacity, lighting and vessel window
are project defaults, not a reconstruction of its binary vrConifg.xml.
Additional HU-based CT presets live in volume_ct_presets.py.
See docs/volume-presets.md for provenance and parameter conventions.
"""
from voxplane.i18n import message as _msg
from types import MappingProxyType

from voxplane.model.dicom_types import WindowLevel
from voxplane.model.volume_models import VolumeBlendMode, VolumePreset
from voxplane.volume_ct_presets import CT_PRESETS


def _rgb_anchors(samples):
    return tuple((index/255, r/255, g/255, b/255) for index, r, g, b in samples)


GRAYSCALE = ((0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0))
BONE_COLORS = _rgb_anchors((
    (0, 0, 0, 0), (32, 56, 39, 9), (64, 112, 78, 18),
    (96, 169, 118, 27), (128, 219, 154, 36), (160, 235, 175, 43),
    (192, 251, 196, 50), (224, 255, 228, 60), (255, 255, 254, 237),
))
VESSEL_COLORS = _rgb_anchors((
    (0, 0, 0, 0), (32, 41, 0, 0), (64, 82, 0, 0),
    (96, 123, 0, 0), (128, 165, 0, 0), (160, 204, 11, 7),
    (192, 239, 65, 39), (224, 255, 126, 92), (255, 255, 248, 247),
))

VOLUME_PRESETS = (
    VolumePreset("general", _msg('text.0004'), "General", GRAYSCALE,
                 tuple((i/16, 0.08*(i/16)**2) for i in range(17))),
    VolumePreset("mip", "MIP", "General", GRAYSCALE, ((0, 0), (1, 1)),
                 blend_mode=VolumeBlendMode.MIP, shade=False),
    VolumePreset("xray", "XRay", "General", GRAYSCALE, ((0, 0), (1, 1)),
                 blend_mode=VolumeBlendMode.ADDITIVE, shade=False),
    VolumePreset("bone", _msg('text.0005'), "CT", BONE_COLORS,
                 ((0, 0), (0.35, 0), (0.45, 0.04), (0.6, 0.25), (1, 0.8)),
                 default_window=WindowLevel(center=300, width=1500), ct_only=True),
    VolumePreset("lung", _msg('text.0006'), "CT", GRAYSCALE,
                 ((0, 0), (0.15, 0), (0.2, 0.05), (0.4, 0.12), (0.65, 0.04), (0.8, 0), (1, 0)),
                 default_window=WindowLevel(center=-400, width=1500), ct_only=True),
    VolumePreset("vessel", _msg('text.0007'), "CTA", VESSEL_COLORS,
                 ((0, 0), (0.1, 0), (0.2, 0.05), (0.5, 0.25), (1, 0.8)),
                 default_window=WindowLevel(center=400, width=700), ct_only=True),
    VolumePreset("mr-general", _msg('mr.volumeGeneral'), "MR", GRAYSCALE,
                 ((0, 0), (.1, 0), (.3, .015), (.6, .06), (1, .15))),
    VolumePreset("mr-bright", _msg('mr.volumeBright'), "MR", GRAYSCALE,
                 ((0, 0), (.5, 0), (.7, .03), (1, .3))),
    VolumePreset("mr-mip", "MR MIP", "MR", GRAYSCALE, ((0, 0), (1, 1)),
                 blend_mode=VolumeBlendMode.MIP, shade=False),
)
# Keep groups contiguous for the menu and stable IDs for existing view state.
VOLUME_PRESETS = tuple(
    preset for group in ("General", "CT", "CTA", "MR")
    for preset in (*VOLUME_PRESETS, *CT_PRESETS) if preset.group == group
)
VOLUME_PRESET_BY_ID = MappingProxyType({preset.preset_id: preset for preset in VOLUME_PRESETS})
