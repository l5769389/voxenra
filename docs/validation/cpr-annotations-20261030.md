# CPR annotations and image bounds — 2026-10-30

Removed the permanent footer from all four CPR cells. The image fills each cell in viewing, drawing and editing states; wheel navigation and double-click behavior are unchanged. Reference images keep Slice, physical position, WW/WL, valid cursor values, direction and scale. Result images show `CPR · THIN` (or projection and thickness), `CROSS-SECTION`, and `s: current / total mm`. `s` is distance along the centerline from its start; the Chinese control panel explicitly says “距起点 … / 全长 …”. The curved output does not invent anatomical direction or a physical scale from a single planar geometry.

Corner numbers use tabular figures. The inline reference selector reserves a fixed physical-coordinate width when deciding whether to wrap; moving between one- and two-digit coordinates no longer changes the annotation row height. Historical and previous-result indications are inside the viewport instead of changing image bounds. Historical plane identity and saved distance persist until the replacement image is accepted, including pending navigation; a historical distance is never paired with the current path's length.

## Automated checks

- Shared annotation, appearance/language, export, PET workspace, manual and CPR regression: 214 passed, before the final pending-history fix (`cpr-annotations-20261030/tests.txt`).
- All CPR tests after that fix: 133 passed (`cpr-annotations-20261030/cpr-final.txt`). Three existing SWIG deprecation warnings only.
- The wrap regression reproduced changing row geometry before the fix. Pending historical reference and cross-section tests both failed before preserving displayed historical state, and pass afterward. A separate read-only review confirmed the historical transition fix.

## Native Qt Quick evidence

Used the isolated Cocoa CPR validation app with synthetic CT and its read-only state snapshot. Screenshot/state pairs in `cpr-annotations-20261030/` show:

- `01-before-scroll`: reference S: 60.64 mm, Slice 62.
- `02-after-scroll`: reference S: 16.64 mm, Slice 18.
- `03-single-digit`: reference I: 0.36 mm, Slice 1.

The coordinate change does not move the selector, Slice row or image bounds. All four footer rows are absent. Both result views display accepted along-path distance, and the Chinese panel distinguishes start distance from full length. The first reference was subsequently restored to the current centerline position through the curved image.

The proposed separate editing/result layouts are a design recommendation only; this patch keeps the four-cell layout. Reconstruction and sampling algorithms are unchanged.
