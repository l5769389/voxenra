"""Fallback gestures shared by slice, montage and native volume views."""
from PySide6.QtCore import Qt

from qt_dicom_viewer.model import InteractionType


def drag_interaction(active: InteractionType, buttons: int, preferences=None) -> InteractionType:
    """Call after any view-specific binding (e.g. registration) claims a drag.

    The selected tool owns the left button. Right zoom is temporary and never
    changes the selected tool. Preserve the existing middle-button binding.
    """
    if buttons & Qt.MouseButton.LeftButton.value:
        return active or InteractionType.WINDOW
    preferences = preferences or {}
    for button, key, default in ((Qt.MouseButton.RightButton, "rightButton", "zoom"),
                                 (Qt.MouseButton.MiddleButton, "middleButton", "selected")):
        if buttons & button.value:
            choice = preferences.get(key, default)
            return active if choice == "selected" else InteractionType.NONE if choice == "none" else InteractionType(choice)
    return InteractionType.NONE
