"""Bounded 2D scene geometry shared by the UI and workspace validation."""
def grid(rows, columns):
    return [dict(row=r, column=c, rowSpan=1, columnSpan=1)
            for r in range(rows) for c in range(columns)]


def placements(key, rows=1, columns=1):
    if key == "custom":
        return rows, columns, grid(rows, columns)
    if "x" in key:
        rows, columns = map(int, key.split("x"))
        return rows, columns, grid(rows, columns)
    # A large viewport with two or three smaller companions.
    side, count = key.split("-")
    count = int(count)
    if side in ("left", "right"):
        main = 0 if side == "left" else 1
        return count, 2, [dict(row=0, column=main, rowSpan=count, columnSpan=1)] + [
            dict(row=r, column=1-main, rowSpan=1, columnSpan=1) for r in range(count)]
    main = 0 if side == "top" else 1
    return 2, count, [dict(row=main, column=0, rowSpan=1, columnSpan=count)] + [
        dict(row=1-main, column=c, rowSpan=1, columnSpan=1) for c in range(count)]


PRESETS = ("1x1", "2x1", "1x2", "2x2", "2x3", "3x2", "3x3", "4x4",
           "top-2", "left-2", "right-2", "bottom-2", "top-3", "left-3", "right-3", "bottom-3")
MODES = ("stack", "axial", "coronal", "sagittal")



def validate_scene(record, series):
    if not isinstance(record, dict):
        raise ValueError("Invalid 2D layout")
    from voxplane.model.ui_models import ViewportDisplaySettings
    if "displayDefaults" in record and not isinstance(record["displayDefaults"], ViewportDisplaySettings):
        raise ValueError("Invalid viewport defaults")
    key = record.get("layout")
    rows, columns = record.get("rows"), record.get("columns")
    if (key not in (*PRESETS, "custom") or type(rows) is not int or type(columns) is not int
            or not 1 <= rows <= 6 or not 1 <= columns <= 6):
        raise ValueError("Invalid 2D layout dimensions")
    expected_rows, expected_columns, positions = placements(key, rows, columns)
    if (rows, columns) != (expected_rows, expected_columns):
        raise ValueError("Invalid 2D layout geometry")
    cells, active = record.get("cells"), record.get("active")
    if (not isinstance(cells, list) or not len(positions) <= len(cells) <= 36
            or type(active) is not int or not 0 <= active < len(positions)):
        raise ValueError("Invalid 2D layout cells")
    for cell in cells:
        if not isinstance(cell, dict):
            raise ValueError("Invalid 2D cell")
        if "display" in cell and not isinstance(cell["display"], ViewportDisplaySettings):
            raise ValueError("Invalid viewport settings")
        uid, mode, modes = cell.get("uid"), cell.get("mode"), cell.get("modes")
        if (uid not in ("", *series) or mode not in MODES or not isinstance(modes, list)
                or any(m not in MODES for m in modes) or len(set(modes)) != len(modes)
                or (uid and ("stack" not in modes or mode not in modes)) or (not uid and modes)):
            raise ValueError("Invalid 2D cell source or orientation")
