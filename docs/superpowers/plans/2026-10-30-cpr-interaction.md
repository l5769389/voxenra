# CPR interaction refinement

> Implement inline with executing-plans; retain the approved manual CPR geometry.

**Goal:** Make placing, confirming and editing a path explicit, and put reconstruction controls above occasional path administration.

**Architecture:** Transient editing state in CprTabController; QML adapts controls to drawing, viewing and editing. Geometry, persisted paths and measurement provenance remain unchanged.

**Tech Stack:** PySide6, Qt Quick, pytest/QTest, native macOS UI verification.

**Spec:** `docs/superpowers/specs/2026-10-29-cpr-design.md` and the user's 2026-10-30 interaction correction request.

## Decisions

- Keep manually placed 3D polylines. Smoothing/automatic vessel tracking would change the validated geometry and is a separate feature.
- New path: click reference images to place points, scroll through slices, Backspace removes the last point, double-click/Enter or the primary confirmation button completes; Escape cancels. Fewer than two points disables confirmation. A double-click must not append a second terminal point.
- Completion returns to viewing. Explicit “Edit path” enables dragging points and clicking a segment to insert. “Done editing” locks the path again; leaving the path panel also exits editing. Cross-section measurement shortcuts never delete path controls.
- Use a distinct connected-node CPR icon, matching pointer artwork, and icon+text action buttons.
- Path selector and new/edit actions stay at the top. Show drawing guidance and point count directly. Rename, LPS coordinates and destructive actions belong in a collapsed path-details group. Section navigation, projection, angle and slab thickness are the normal controls; thin projection disables thickness. Sampling and interval measurements are separate disclosures.

## Tasks

- [x] Add failing controller and real QML event tests for completion lock, explicit editing, double-click deduplication, deletion ownership and two-point confirmation.
- [x] Implement transient state and pointer dispatch. Keep drag cancellation and history semantics; add no persistence schema fields.
- [x] Reorganize CprPanel and add CPR artwork, visible localized guidance, accessible parameter labels and reference-view mode hints.
- [x] Run CPR and shared interaction/toolbar/i18n regressions. Verify native drawing, double-click/keyboard confirmation, editing, cancellation and the panel at 1280×720. Record evidence and local changes.

## Review focus

Rapid double-click order, pending rendering while exiting edit mode, tool/path changes, loaded workspace default mode, narrow panel and English labels. Existing Slicer geometry/measurement validation remains applicable because no sampling algorithm changes.

## Completion record

Implementation and native verification are documented in `docs/validation/cpr-interaction-20261030.md`. The final review coverage gap (Enter confirming a suspended draft) was reproduced and fixed. Reference footer bounds are stable across modes; endpoint jitter is ignored within the visible point hit target without suppressing points on another slice. Keep the existing CPR branch and worktree for continued user review.

## Viewport follow-up: 2026-10-30

The user requests fewer repeated corner fields and navigation controls, retaining wheel paging and double-click focus. Both reference images have equal editing capability: replace primary/auxiliary headings with the existing 2D inline plane selector. Remove fullscreen buttons and vertical slice rails. Keep orientation, physical scale, windowing, reference position/slice, accepted projection and path distance; omit repeated identity/acquisition metadata and meaningless output slice counts. Drawing double-click retains exclusive ownership of confirmation, and curve/freehand measurements retain their completion gesture. Verify real QML events, export, other workspaces' overlays and native UI/state together. No CPR resampling or persisted geometry changes.
