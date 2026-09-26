"""Theme data shared by Qt widgets and QML (no application state here)."""
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def _theme_data():
    source = files("qt_dicom_viewer").joinpath("qml/theme/palettes.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("formatVersion") != 1:
        raise ValueError("Unsupported built-in theme format")
    defaults = data["defaults"]
    for overrides in data["themes"].values():
        if set(overrides) - set(defaults):
            raise ValueError("Theme override contains an unknown color role")
    if set(defaults) & set(data["imaging"]):
        raise ValueError("UI and image color roles must be separate")
    return data


def palette_for(theme: str) -> dict[str, str]:
    """Return a fresh complete palette; omitted roles use the base palette."""
    data = _theme_data()
    return {**data["defaults"], **data["themes"].get(theme, {}), **data["imaging"]}
