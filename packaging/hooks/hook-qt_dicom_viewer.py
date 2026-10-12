"""Collect live UI assets without the superseded PNG icon design originals."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "src/qt_dicom_viewer/qml"
datas = []
for source in sorted(root.rglob("*")):
    if not source.is_file():
        continue
    relative = source.relative_to(root)
    if relative.parts[:2] == ("assets", "icons") and source.suffix.lower() == ".png":
        continue
    if "__pycache__" in relative.parts or source.name.startswith("."):
        continue
    datas.append((str(source), str(Path("qt_dicom_viewer/qml") / relative.parent)))

# Executed by the separately configured Python, not imported into the bundle.
bridge = root.parent / "infrastructure/totalsegmentator_bridge.py"
datas.append((str(bridge), "qt_dicom_viewer/infrastructure"))
