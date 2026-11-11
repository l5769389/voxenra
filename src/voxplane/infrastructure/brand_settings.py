"""VoxPlane identity and one-time, non-destructive migration of released user data."""
import json
import logging
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QStandardPaths, QSaveFile, QIODevice

logger = logging.getLogger(__name__)
APP_NAME = "VoxPlane"
# Compatibility only: identities used by previously released applications.
PREVIOUS_APP_NAME = "Voxenra"
LEGACY_ORGANIZATION = "QtDicomViewer"
LEGACY_APPLICATION = "Qt DICOM Viewer"
MIGRATION_MARKER = "brand-migration-v1.json"
PREFERENCE_FILES = ("display-settings.json", "pacs.json", "window-presets.json",
                    "dialog-locations.json", "favorite-directories.json", "recent-image-paths.json")


def _copy_file(old: Path, new: Path) -> bool:
    if old == new or new.exists() or not old.is_file() or old.is_symlink():
        return True
    try:
        return _write_file(new, old.read_bytes())
    except OSError:
        logger.exception("Could not migrate legacy file %s", old.name)
        return False


def _write_file(path: Path, contents: bytes) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(str(path))
        if not output.open(QIODevice.WriteOnly):
            raise OSError(output.errorString())
        if output.write(contents) != len(contents):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())
        return True
    except OSError:
        logger.exception("Could not migrate legacy file %s", path.name)
        return False


def migrate_preferences(source: Path, destination: Path) -> bool:
    results = [_copy_file(source / name, destination / name)
               for name in PREFERENCE_FILES]
    return all(results)


def _storage_locations(organization: str, application: str) -> tuple[Path, Path]:
    QCoreApplication.setOrganizationName(organization)
    QCoreApplication.setApplicationName(application)
    return tuple(Path(QStandardPaths.writableLocation(kind)) for kind in
                 (QStandardPaths.AppConfigLocation, QStandardPaths.AppLocalDataLocation))


def configure_storage_identity() -> None:
    # Most recent identity first: older files must never replace newer choices.
    sources = [_storage_locations(PREVIOUS_APP_NAME, PREVIOUS_APP_NAME),
               _storage_locations(LEGACY_ORGANIZATION, LEGACY_APPLICATION)]
    config, data = _storage_locations(APP_NAME, APP_NAME)
    marker = config / MIGRATION_MARKER
    completed = set()
    if marker.is_file():
        try:
            progress = json.loads(marker.read_bytes())
            if (not isinstance(progress, dict) or progress.get("version") != 1
                    or type(progress.get("complete")) is not bool
                    or not isinstance(progress.get("completed"), list)
                    or any(not isinstance(key, str) for key in progress["completed"])):
                raise ValueError("Invalid migration journal")
            if progress["complete"]:
                return
            completed.update(progress["completed"])
        except (OSError, ValueError):
            # Do not reintroduce previously dismissed data if progress is unreadable.
            logger.exception("Could not read migration journal; old files remain untouched")
            return

    def save_progress(complete=False):
        return _write_file(marker, json.dumps(dict(version=1, complete=complete,
                                                  completed=sorted(completed))).encode("utf-8"))

    if not marker.exists() and not save_progress():
        return  # Require durable progress before importing any dismissible data.
    candidates = {}
    for old_config, old_data in sources:
        files = [("config/" + name, old_config / name, config / name)
                 for name in PREFERENCE_FILES]
        files.extend(("data/" + name, old_data / name, data / name)
                     for name in ("workspace-recovery.voxworkspace", "recent-workspaces.json"))
        files.extend(("data/languages/" + old.name, old, data / "languages" / old.name)
                     for old in (old_data / "languages").glob("*.json"))
        for key, old, new in files:
            if old.is_file():
                # Select the newest available source once, even if its copy fails.
                candidates.setdefault(key, (old, new))
    for key, (old, new) in candidates.items():
        if key in completed:
            continue
        if _copy_file(old, new):
            completed.add(key)
            if not save_progress():
                return
    save_progress(complete=all(key in completed for key in candidates))
