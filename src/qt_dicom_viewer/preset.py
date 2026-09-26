from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.model import WindowPreset

# Display starting points, not acquisition protocols. Added presets follow:
# https://studycast.zendesk.com/hc/en-us/articles/49402662648084-WW-WC-Presets-for-CT
# https://help.collectiveminds.health/ct-windowing-and-level (posterior fossa)
CT_WINDOW_PRESETS = (
    WindowPreset(
        preset_id="ct-brain",
        label=_msg('text.0000'),
        center=40,
        width=80,
    ),
    WindowPreset(
        preset_id="ct-lung",
        label=_msg('text.0001'),
        center=-600,
        width=1500,
    ),
    WindowPreset(
        preset_id="ct-bone",
        label=_msg('text.0002'),
        center=300,
        width=1500,
    ),
    WindowPreset(
        preset_id="ct-soft-tissue",
        label=_msg('text.0003'),
        center=40,
        width=400,
    ),
    WindowPreset(preset_id="ct-mediastinum", label=_msg("windowPreset.mediastinum"), width=350, center=50),
    WindowPreset(preset_id="ct-abdomen", label=_msg("windowPreset.abdomen"), width=400, center=50),
    WindowPreset(preset_id="ct-liver", label=_msg("windowPreset.liver"), width=150, center=30),
    WindowPreset(preset_id="ct-subdural", label=_msg("windowPreset.subdural"), width=210, center=100),
    WindowPreset(preset_id="ct-brain-narrow", label=_msg("windowPreset.brain-narrow"), width=40, center=40),
    WindowPreset(preset_id="ct-posterior-fossa", label=_msg("windowPreset.posterior-fossa"), width=250, center=80),
    WindowPreset(preset_id="ct-temporal-bone", label=_msg("windowPreset.temporal-bone"), width=2800, center=600),
    WindowPreset(preset_id="ct-spine-soft-tissue", label=_msg("windowPreset.spine-soft-tissue"), width=250, center=50),
    WindowPreset(preset_id="ct-spine-bone", label=_msg("windowPreset.spine-bone"), width=1800, center=400),
)
