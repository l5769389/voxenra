# CPR Local UI Workflow Implementation and Verification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the complete CPR workflow operable and verify it through the native local UI, from entering a series to restoring saved work and exporting results.

**Architecture:** A dedicated CPR tab composes the existing image viewport, measurement, display and export components. The existing render worker supplies a validated cached volume; a single-concurrency CPR worker samples immutable requests with generation checks. Session edits are value snapshots, independent of computed images.

**Tech Stack:** Python, NumPy, PySide6/Qt Quick, existing QtTest harness and native computer-use tools.

**Spec:** `docs/superpowers/specs/2026-10-29-cpr-design.md` (phases B–D). The active user goal requires the actual local workflow, so phase A alone is insufficient. Local validation is not a Windows or clinical release claim.

## Global Constraints

- Preserve phase-A geometry and source LPS mm conventions; do not introduce implicit smoothing or ordinary quantitative measurements on curved images.
- Two reference views, a curved view, a perpendicular cross-section; manual multi-path drawing/editing, undo/redo, position linkage and linked windowing.
- Immutable path/settings snapshots; one running and one newest pending request per tab, global single CPR compute concurrency, cancellation and generation rejection.
- Existing volume cache is accessed only through its owner worker; no whole-volume copy and no concurrent in-place source edits.
- Close retains results; workspace saves sources/edits/views, never CPR image caches; v1 documents migrate to v2 before validation.
- Cross-section measurements retain their actual creation plane and source identity, even after editing or deleting the current path.
- Actual native UI input plus visible and persisted state is required for completion. Passing Python tests alone is insufficient.

## Review Focus

- A rapid drag followed by undo or tab closure must not publish late geometry or dispose a running worker's signal owner.
- A selected point outside the current slice must keep its normal coordinate during planar dragging.
- Restoring an old cross-section measurement after a path edit must show its original physical plane, not a same-index new plane.
- A closed CPR tab must survive workspace save/reopen and keep paths editable; source mismatch must retain records with a clear error.
- Preview or failed/stale reconstruction must never be exported or used for quantitative measurement.

### Task 1: Session state and bounded worker

**Files:** create `core/cpr_session.py`, `ui/workers/cpr_render_task.py`, `tests/test_cpr_session.py`, `tests/test_cpr_render_task.py`.

**Interfaces:** session dictionaries validate through `validate_cpr_session(state)`; source identity includes series UID, frame-of-reference UID and volume fingerprint. `CprRenderInput` contains generation, volume, optional path, settings, position, reference planes/centers, preview and optional cached curve. `compute_cpr(request) -> CprRenderOutput` returns two reference slices plus optional curved/cross-section result. `CprRenderQueue.submit(request)`, `.cancel()`, `.close()` emit only current results and retain at most one pending request.

- [x] Write RED tests for session validation, immutable model persistence, reference/cross linkage, preview, cancellation, coalescing and close.
- [x] Run `.venv/bin/python -m pytest tests/test_cpr_session.py tests/test_cpr_render_task.py -q`. Expected: missing modules, then PASS after implementation.
- [x] Implement value validation and pure compute function, then Qt scheduling with the existing cancellation context.
- [x] Commit `feat(cpr): add persistent sessions and bounded background reconstruction`.

### Task 2: Operable tab, viewport and path UI

**Files:** create `ui/controller/tab/cpr_tab_controller.py`, `ui/controller/viewport/image_2d/cpr_viewport_controller.py`, `qml/sections/center/viewportArea/CprPage.qml`, `CprPathOverlay.qml`, `qml/sections/right/panels/CprPanel.qml`, `tests/test_cpr_controller.py`, `tests/test_cpr_qml.py`; modify tab/tool types, tool catalog/priorities, workspace factory, CenterPanel/Viewport/ToolDetailPanel, language catalogs and Qt resource manifest.

**Interfaces:** `CprTabController(TabConfig, parent)` uses standard TabController lifetime/history interfaces and exposes `cprController` for the page/panel. Viewport hooks route CPR pointer actions before generic measurements while preserving right-button zoom, wheel navigation and ordinary view controls. Curve view has no plane geometry and rejects all ordinary measurement paths.

- [x] Write RED controller and rendered QML tests for opening/reuse, multi-path create/finish/cancel, point select/drag/insert/delete, one drag per undo, reference plane switches, cursor/section linkage, linked windowing without resampling, viewport maximize and invalid inputs.
- [x] Implement the dedicated controller and four views, then QML controls/overlay and entry points (MPR tool group and series context menu).
- [x] Run `QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_isolated.py tests/test_cpr_controller.py tests/test_cpr_qml.py --output build/cpr-ui-tests`. Expected: PASS with no QML load/binding errors.
- [x] Commit `feat(cpr): add interactive reconstruction workspace`.

### Task 3: History, measurement provenance, workspace and export

**Files:** modify `ui/workspace_snapshot.py`, `core/workspace_state.py`, `core/workspace_document.py`, `ui/controller/workspace_controller.py`, `ui/controller/workspace_document_controller.py`, `ui/measurement_source.py`, export integration and CPR controller; create `tests/test_cpr_persistence.py`, `tests/test_cpr_measurement.py`, `tests/test_cpr_export.py`.

**Interfaces:** a true cross-section converts to an existing `MprRenderRequest` with its captured frame/grid; source includes CPR path revision and source fingerprint. Snapshots contain `cpr` session state and existing viewport/measurement state. v1→v2 migration is explicit; older files without CPR stay readable. Export uses full-resolution current-generation results and the existing anonymous PNG workflow.

- [x] Write RED tests for undo/redo, deletion restoration, closed-tab retention, v1 migration, v2 roundtrip, missing/changed source, measurement navigation after path edits, privacy and preview export rejection.
- [x] Implement the adapters and native save/open/export flows; preserve exact geometric sources and validate restored values before applying them.
- [x] Run the three CPR files plus existing workspace persistence/retention and measurement-source regressions. Expected: PASS; no cached image arrays in saved documents.
- [x] Commit `feat(cpr): retain measurements and restore reconstruction workspaces`.

### Task 4: Complete native UI acceptance and fix observed defects

**Files:** add a synthetic DICOM/native-app test harness under `tests/manual/`, a CPR operation manual entry and `docs/validation/cpr-ui-20261029.md` with per-step evidence.

**Interfaces:** harness starts the actual application with isolated user settings, writes read-only state observations, and accepts ordinary Qt/native input. It is not an alternate CPR implementation.

- [x] Generate an identified synthetic curved-tube DICOM series, launch native application and import through the UI.
- [x] Physically operate both entries, draw a cross-plane path, finish, edit/insert/delete, cancel, create/switch/rename/delete multiple paths, undo/redo, change plane/position/angle/slab/precision, adjust window/zoom/pan, measure reference and cross-section, verify curved measurement restriction, maximize/focus.
- [x] Close/reopen CPR, save workspace, restart/open it, return to an older measurement after path edit, export CPR/cross/combined PNG and inspect files. Exercise incomplete/invalid paths, rapid changes and closure during reconstruction.
- [x] Inspect light/dark, narrow window and available local scale configurations. Capture visible screenshots and matching controller/document/file state; record any unverified item as incomplete rather than passing it.
- [x] Run targeted tests after fixes, then full isolated regression. Preserve the known pristine-baseline favorite-directory offscreen failure separately; do not mistake it for CPR evidence.
- [x] Fresh whole-branch review, fix important defects with RED→GREEN; complete the goal only after every native acceptance requirement has direct evidence.

## Execution record

This goal remains active across turns until Task 4 is actually verified. Do not replace it with a smaller core-only or automated-only milestone. No merge, package or release is requested.
