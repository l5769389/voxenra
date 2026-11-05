# CPR sampling guide linkage Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks inline. Preserve the current checkout's existing changes.

**Goal:** Link the current CPR sampling position and direction across all four viewports using cyan point/line/projection markers.

**Architecture:** Derive reference-view markers from the accepted cross-section's center and column direction, using the accepted CPR width. Project this finite patient-space line into each reference plane. Render coplanar lines solid, collapsed projections as visible points, and oblique/off-plane projections dashed with a localized projection label. Use the same cyan color for the curved result's station column and cross-section guide.

**Tech Stack:** Python, NumPy, PySide6, QML Canvas.

**Spec:** The user-approved design in this conversation: show the selected path's sampling direction in both reference views, preserve point markers, distinguish projections, and share the existing sampling-guide visibility switch.

## Constraints and review focus

- Retain path drawing/editing/completed colors and interval A/B labels.
- Rendering only: preserve reconstruction, measurements, input dispatch, and path geometry.
- Use displayed data rather than controls awaiting asynchronous reconstruction.
- Suppress guides during a new path draft, on historical planes, and for a different selected path.
- Check orthogonal/oblique/offset reference planes, actual physical width, transforms, and guide visibility.

## Tasks

- [x] 1. Add failing projection and controller tests, then implement a small patient-space guide helper and integrate accepted-result metadata.
- [x] 2. Render cyan points/lines/projection labels in reference views; unify curved station color and visibility. Verify actual painted pixels and interaction remains available.
- [x] 3. Update localized help/manual; run CPR regression and native UI checks, capture and inspect screenshots for 0°/45°/90° and reference-plane switching.

## Verification

- Final isolated regression: 14 files, 257 passed, no failures/errors/skips.
- Native Cocoa QML checks: 3 passed, including painted cyan pixels, 0°/45°/90°, reference-plane selection, transforms, visibility, collapsed oblique dashes, and panned projection labels.
- Fresh-context review found two rendering edge cases. Both were reproduced with failing UI tests, fixed, and reviewed again with no further actionable findings.
- Evidence: `build/cpr-guides-20261105/review.md`, `regression-final/results.json`, `native-final.xml`, and native screenshots under `native-final/test_sampling_guides_show_poin0/`.

No release or branch changes are part of this task.

## Follow-up: clarify endpoints and clipping

User approved the three visual refinements after reviewing the live four-view screenshot. The previous yellow station line was intentionally recolored cyan; the completed centerline retains its configured color (yellow by default).

- [x] In `CprPathOverlay.qml`, use one 1.5 px cyan / 2.5 px dark-outline stroke for sampling markers, including the cross-section. Label end-on samples as “取样线·端视” with English and Portuguese equivalents.
- [x] Add outward chevrons where the cross-section sampling line continues outside its field of view; preserve end caps where the actual ends are visible. Keep markers screen-sized and aligned through rotation/mirroring. Verify painted pixels for widths below/equal to/above the cross-section field and the guide visibility switch in `tests/test_cpr_qml.py` before and after implementation.
- [x] Update sampling help/manual, run the relevant CPR and localization regression, inspect native screenshots, and record results. Reuse the current checkout and preserve unrelated changes.

Follow-up verification: 261 regression tests passed across 14 files; 7 native Cocoa checks passed. The new tests observed RED→GREEN for absent continuation wings, false clipping of a complete endpoint just inside the viewport, and a zoomed small in-plane line incorrectly labeled end-on. Evidence is in `build/cpr-guide-polish-20261105/`.

## Follow-up: reference slice changes with unchanged CPR distance

The user reports a plain cross-section click moving the coronal slice while s stays 0. Plain clicks after Enter and double-click completion did not reproduce in a real Main.qml Cocoa window. A confirmed related bug is that a substep scroll drag emits the current slice index and `navigate_view` calls `setPositionMm` anyway; that recenters references onto the first path point without changing s. A repeated index request also reproduces it directly. Keep the distinction explicit in the report.

- [x] Add failing controller and full-window tests for unchanged result index/substep drag. Cover both completion gestures, ordinary activation, real navigation, and returning to the displayed sample during an in-flight request.
- [x] Ignore unchanged result-index navigation only when the current result is ready and the view is not historical. Preserve deliberate `setPositionMm` location and pending/historical navigation semantics.
- [x] Verify native visible slice labels against state and run CPR interaction/persistence regression. Explain the dashed cyan ring as an off-plane projection with dark contrast outlines; retain the agreed projection styling.

Click-audit verification: 149 tests across 10 CPR-related files and 2 native full-window tests passed. Native captures preserve coronal 49/96 and s=0 through activation and substep drag; actual navigation changes s and locates the corresponding coronal plane. Independent read-only review found no actionable guard issue. The user's exact pure-click trigger remains unconfirmed: both native completion routes preserved the slice on click, and the installed app accessible through CUA showed a recovery dialog rather than the reported CPR session. Details: `build/cpr-click-audit-20261105/review.md`.

## Follow-up: initial sample alignment and transparent projection dashes

The user clarified that the jump occurs on the first small movement of the lower-left sampling line. New paths start at s=0 but reference slices still retain the volume midpoint; the first actual navigation then aligns them to the path. Align both reference slices when completing or selecting a path, including the fallback path after deletion. Preserve independent reference browsing and restored workspace views.

- [x] Verify failing initial-alignment and path-switch/deletion tests, then align references to the first sample at those explicit transitions.
- [x] Remove black underlays from projected cyan guide strokes and dashed rings; keep transparent gaps and retain solid-guide contrast.
- [x] Verify native drawing/completion and first small sampling-line movement, existing no-op navigation, rendering, and persistence. Update help and record review evidence.

Repeated same-series tabs currently follow the user's earlier explicit “always new” choice. A new preference question is pending; do not change this policy without their answer.

Verification: three controller cases failed before the fix, then passed. The final isolated suite passed 269 tests in 14 files with no failures/errors/skips; 7 native Cocoa tests passed. Native captures show coronal 21/96 at completion (s=0) and 22/96 after the first 0.499 mm left-lower sample movement. Independent review found no actionable issue. Evidence: `build/cpr-initial-alignment-20261105/review.md`.
