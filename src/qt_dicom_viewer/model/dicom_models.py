from enum import StrEnum
from typing import TypeAlias


class TabType(StrEnum):
    TWO_D = "2d"
    COMPARE_2D = "compare2d"
    COMPARE_MPR = "comparempr"
    MONTAGE = "montage"
    MPR = "mpr"
    CPR = "cpr"
    THREE_D = "3d"
    FOUR_D = "4d"
    TAG = "tag"
    PETCT_FUSION = "petctfusion"
    MANUAL = "manual"
    SETTINGS = "settings"
    PACS = "pacs"


class TwoDViewType(StrEnum):
    STACK = "stack"
    MONTAGE = "montage"
    PET_MIP = "pet-mip"
    CPR = "cpr"


class MprPlane(StrEnum):
    AXIAL = "axial"
    SAGITTAL = "sagittal"
    CORONAL = "coronal"


class MprProjectionMode(StrEnum):
    MIN_IP = "minip"
    MIP = "mip"
    MEAN = "mean"
    SUM = "sum"


class VolumeViewType(StrEnum):
    VOLUME = "volume"


ViewportType: TypeAlias = MprPlane | TwoDViewType | VolumeViewType


class ToolType(StrEnum):
    SEGMENTATION = "segmentation"
    VOI = "voi"
    WINDOW = "window"
    CT_WINDOW = "ct-window"
    PET_WINDOW = "pet-window"
    REGISTRATION = "registration"
    FUSION_BLEND = "fusion-blend"
    PAN = "pan"
    ZOOM = "zoom"
    SCROLL = "scroll"
    MEASURE = "measure"
    ANNOTATE = "annotate"
    PSEUDOCOLOR = "pseudocolor"
    VIEWPORT_SETTINGS = "viewport-settings"
    ROTATE = "rotate"
    MIP = "mip"
    INVERT = "invert"
    MPR_ROTATE_3D = "mpr-rotate-3d"
    MPR_LAYOUT = "mpr-layout"
    OPEN_CPR = "open-cpr"
    CPR_PATH = "cpr-path"
    VOLUME_ROTATE = "volume-rotate"
    VOLUME_DIRECTION = "volume-direction"
    VOLUME_PRESET = "volume-preset"
    VOLUME_BED = "volume-bed"
    VOLUME_CROP = "volume-crop"
    PLAY = "play"
    SLICE_PLAY = "slice-play"
    IMPORT = "import"
    EXPORT = "export"
    SERVICE = "service"
    RESET = "reset"
