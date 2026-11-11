"""Collect live UI assets without the superseded PNG icon design originals."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "src/voxplane/qml"
datas = []
for source in sorted(root.rglob("*")):
    if not source.is_file():
        continue
    relative = source.relative_to(root)
    if relative.parts[:2] == ("assets", "icons") and source.suffix.lower() == ".png":
        continue
    if "__pycache__" in relative.parts or source.name.startswith("."):
        continue
    datas.append((str(source), str(Path("voxplane/qml") / relative.parent)))

# Executed by the separately configured Python, not imported into the bundle.
for name in ("totalsegmentator_bridge.py", "posix_inference_supervisor.py"):
    helper = root.parent / "infrastructure" / name
    datas.append((str(helper), "voxplane/infrastructure"))
