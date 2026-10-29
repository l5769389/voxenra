from qt_dicom_viewer.i18n import message as _msg
from dataclasses import dataclass

from .dicom_models import TabType, ToolType
from .ui_models import InteractionType, ToolBehavior


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_type: ToolType  # 一级工具类型
    label: str           # 一级工具名称
    icon_name: str       #  icon样子
    behavior: ToolBehavior   #是打开面板不触发功能， 还是触发长期功能。 还是及触发面板又触发功能。 还是一次性指令。

    default_interaction: InteractionType = InteractionType.NONE
    command: str | None = None
    supported_tab_types: frozenset[TabType] | None = None
    reset_label: str | None = None
    enabled: bool = True


TOOL_CATALOG: tuple[ToolDefinition, ...] = (
    ToolDefinition(ToolType.OPEN_CPR, "CPR", "nav-view-mpr", ToolBehavior.COMMAND,
                   command="workspace:open-cpr", supported_tab_types=frozenset((TabType.MPR,))),
    ToolDefinition(ToolType.CPR_PATH, "CPR", "nav-view-mpr", ToolBehavior.PANEL,
                   supported_tab_types=frozenset((TabType.CPR,))),
    ToolDefinition(ToolType.SEGMENTATION, _msg('text.0276'), "segmentation", ToolBehavior.INTERACTION_PANEL,
                   InteractionType.SEGMENTATION, supported_tab_types=frozenset((TabType.MPR, TabType.FOUR_D))),
    ToolDefinition(ToolType.VOI, "VOI", "voi", ToolBehavior.INTERACTION_PANEL,
                   InteractionType.VOI, supported_tab_types=frozenset((TabType.MPR, TabType.FOUR_D))),
    ToolDefinition(ToolType.CT_WINDOW, _msg('text.0277'), "window", ToolBehavior.INTERACTION_PANEL,
                   default_interaction=InteractionType.WINDOW,
                   supported_tab_types=frozenset((TabType.PETCT_FUSION,)), reset_label=_msg('text.0278')),
    ToolDefinition(ToolType.PET_WINDOW, _msg('text.0279'), "pet-window", ToolBehavior.INTERACTION_PANEL,
                   default_interaction=InteractionType.WINDOW,
                   supported_tab_types=frozenset((TabType.PETCT_FUSION,)), reset_label=_msg('text.0280')),
    ToolDefinition(
        tool_type=ToolType.REGISTRATION,
        label=_msg('text.0281'),
        icon_name="registration",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.PETCT_FUSION,)),
        reset_label=_msg('text.0282'),
    ),
    ToolDefinition(
        tool_type=ToolType.FUSION_BLEND,
        label=_msg('text.0283'),
        icon_name="fusion",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.PETCT_FUSION,)),
        reset_label=_msg('text.0284'),
    ),
    ToolDefinition(
        tool_type=ToolType.WINDOW,
        label=_msg('mapping.title'),
        icon_name="window",
        behavior=ToolBehavior.INTERACTION_PANEL,
        default_interaction=InteractionType.WINDOW,
        reset_label=_msg('text.0286'),
    ),
    ToolDefinition(
        tool_type=ToolType.SCROLL,
        label=_msg('text.0287'),
        icon_name="scroll",
        behavior=ToolBehavior.INTERACTION_PANEL,
        default_interaction=InteractionType.SCROLL,
        reset_label=_msg('text.0288'),
    ),
    ToolDefinition(
        tool_type=ToolType.PAN,
        label=_msg('text.0289'),
        icon_name="pan",
        behavior=ToolBehavior.INTERACTION,
        default_interaction=InteractionType.PAN,
        reset_label=_msg('text.0290'),
    ),
    ToolDefinition(
        tool_type=ToolType.ZOOM,
        label=_msg('text.0033'),
        icon_name="zoom",
        behavior=ToolBehavior.INTERACTION_PANEL,
        default_interaction=InteractionType.ZOOM,
        reset_label=_msg('text.0291'),
    ),
    ToolDefinition(
        tool_type=ToolType.MEASURE,
        label=_msg('text.0292'),
        icon_name="measure",
        behavior=ToolBehavior.PANEL,
        default_interaction=InteractionType.MEASURE_LENGTH,
        reset_label=_msg('text.0293'),
    ),
    ToolDefinition(
        tool_type=ToolType.ROTATE,
        label=_msg('text.0294'),
        icon_name="rotate",
        behavior=ToolBehavior.PANEL,
        reset_label=_msg('text.0295'),
    ),
    ToolDefinition(
        tool_type=ToolType.MIP,
        label="MIP",
        icon_name="mip",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.MPR, TabType.FOUR_D)),
        reset_label=_msg('text.0296'),
    ),
    ToolDefinition(
        tool_type=ToolType.INVERT,
        label=_msg('text.0297'),
        icon_name="invert",
        behavior=ToolBehavior.COMMAND,
        supported_tab_types=frozenset((TabType.MONTAGE,)),
        enabled=False,
    ),
    ToolDefinition(
        tool_type=ToolType.MPR_ROTATE_3D,
        label=_msg('text.0298'),
        icon_name="rotate-3d",
        behavior=ToolBehavior.INTERACTION,
        default_interaction=InteractionType.MPR_ROTATE_3D,
        supported_tab_types=frozenset((TabType.MPR, TabType.FOUR_D)),
        reset_label=_msg('text.0299'),
    ),
    ToolDefinition(
        tool_type=ToolType.MPR_LAYOUT,
        label=_msg("layout.title"),
        icon_name="layout-quad",
        behavior=ToolBehavior.PANEL,
        default_interaction=InteractionType.NONE,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
    ),
    ToolDefinition(
        tool_type=ToolType.VOLUME_ROTATE,
        label=_msg('text.0294'),
        icon_name="rotate-3d",
        behavior=ToolBehavior.INTERACTION,
        default_interaction=InteractionType.VOLUME_ROTATE,
        supported_tab_types=frozenset((TabType.THREE_D,)),
        reset_label=_msg('text.0295'),
    ),
    ToolDefinition(
        tool_type=ToolType.VOLUME_DIRECTION,
        label=_msg('text.0300'),
        icon_name="volume-direction",
        behavior=ToolBehavior.PANEL,
        default_interaction=InteractionType.VOLUME_ROTATE,
        supported_tab_types=frozenset((TabType.THREE_D,)),
        reset_label=_msg('text.0301'),
    ),
    ToolDefinition(
        tool_type=ToolType.VOLUME_PRESET,
        label=_msg('text.0302'),
        icon_name="palette",
        behavior=ToolBehavior.PANEL,
        default_interaction=InteractionType.VOLUME_ROTATE,
        supported_tab_types=frozenset((TabType.THREE_D,)),
        reset_label=_msg('text.0303'),
    ),
    ToolDefinition(
        tool_type=ToolType.VOLUME_BED,
        label=_msg('text.0304'),
        icon_name="remove-bed",
        behavior=ToolBehavior.TOGGLE,
        command="volume:toggle-bed",
        supported_tab_types=frozenset((TabType.THREE_D,)),
    ),
    ToolDefinition(
        tool_type=ToolType.VOLUME_CROP,
        label=_msg('text.0305'),
        icon_name="volume-crop",
        behavior=ToolBehavior.INTERACTION_PANEL,
        default_interaction=InteractionType.VOLUME_CROP,
        supported_tab_types=frozenset((TabType.THREE_D,)),
        reset_label=_msg('text.0306'),
    ),
    ToolDefinition(
        tool_type=ToolType.ANNOTATE,
        label=_msg('text.0307'),
        icon_name="annotate",
        behavior=ToolBehavior.INTERACTION_PANEL,
        default_interaction=InteractionType.ANNOTATE_ARROW,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
        reset_label=_msg('text.0308'),
    ),
    ToolDefinition(
        tool_type=ToolType.PSEUDOCOLOR,
        label=_msg('text.0309'),
        icon_name="pseudocolor",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
        reset_label=_msg('text.0310'),
    ),
    ToolDefinition(
        tool_type=ToolType.VIEWPORT_SETTINGS,
        label=_msg('text.0311'),
        icon_name="viewport-settings",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
        reset_label=_msg('text.0312'),
    ),
    ToolDefinition(
        tool_type=ToolType.PLAY,
        label=_msg('text.0313'),
        icon_name="cine-play",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
    ),
    ToolDefinition(ToolType.SLICE_PLAY, _msg("playback.currentPhase"), "cine-play", ToolBehavior.PANEL,
                   supported_tab_types=frozenset((TabType.FOUR_D,))),
    ToolDefinition(
        tool_type=ToolType.SERVICE,
        label=_msg('text.0314'),
        icon_name="service",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.TWO_D,)),
    ),
    ToolDefinition(
        tool_type=ToolType.IMPORT, label=_msg('seg.importTool'), icon_name="import",
        behavior=ToolBehavior.PANEL,
        supported_tab_types=frozenset((TabType.TWO_D, TabType.MPR, TabType.FOUR_D)),
    ),
    ToolDefinition(
        tool_type=ToolType.EXPORT, label=_msg('text.0315'), icon_name="export",
        behavior=ToolBehavior.PANEL,
    ),
    ToolDefinition(
        tool_type=ToolType.RESET,
        label=_msg('text.0316'),
        icon_name="reset",
        behavior=ToolBehavior.COMMAND,
        command="viewport:reset",
    ),
)

TOOL_DEFINITIONS: dict[ToolType, ToolDefinition] = {
    definition.tool_type: definition
    for definition in TOOL_CATALOG
}


@dataclass(frozen=True, slots=True)
class PlaceholderToolDefinition:
    """仅用于展示的规划入口，不注册为可执行工具。"""

    key: str
    label: str
    supported_tab_types: frozenset[TabType]


PLACEHOLDER_TOOLS: tuple[PlaceholderToolDefinition, ...] = ()

@dataclass(frozen=True, slots=True)
class ToolActionDefinition:
    action: str
    label: str
    icon_name: str


# 服务入口分别启动手动 MTF ROI 和自动水模 QA。
SERVICE_ACTIONS = (
    ToolActionDefinition(action="service:mtf", label="MTF", icon_name="mtf"),
    ToolActionDefinition(action="service:fwhm", label="FWHM", icon_name="fwhm"),
    ToolActionDefinition(action="service:qa", label="QA", icon_name="qa"),
)


ROTATE_ACTIONS = (
    ToolActionDefinition(
        action="rotate:mirror-h",
        label=_msg('text.0317'),
        icon_name="mirror-h",
    ),
    ToolActionDefinition(
        action="rotate:mirror-v",
        label=_msg('text.0318'),
        icon_name="mirror-v",
    ),
    ToolActionDefinition(
        action="rotate:cw90",
        label=_msg('text.0319'),
        icon_name="rotate-cw90",
    ),
    ToolActionDefinition(
        action="rotate:ccw90",
        label=_msg('text.0320'),
        icon_name="rotate-ccw90",
    ),
)

MEASURE_ACTIONS = (
    ToolActionDefinition(
        action= InteractionType.MEASURE_LENGTH,
        label=_msg('text.0321'),
        icon_name="measure-line",
    ),
    ToolActionDefinition(
        action=InteractionType.MEASURE_ANGLE,
        label=_msg('text.0322'),
        icon_name="measure-angle",
    ),
    ToolActionDefinition(
        action=InteractionType.MEASURE_RECT,
        label=_msg('text.0323'),
        icon_name="measure-rect",
    ),
    ToolActionDefinition(
        action=InteractionType.MEASURE_ELLIPSE,
        label=_msg('text.0324'),
        icon_name="measure-ellipse",
    ),
    ToolActionDefinition(action=InteractionType.MEASURE_CURVE, label=_msg("measurement.curve"), icon_name="measure-curve"),
    ToolActionDefinition(action=InteractionType.MEASURE_FREEHAND, label=_msg("measurement.freehand"), icon_name="measure-freehand"),
)
