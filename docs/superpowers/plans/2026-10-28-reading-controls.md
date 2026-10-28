# Reading Controls Implementation Plan

> **For agentic workers:** Use focused parallel implementation for independent tasks, then integrated review and verification. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the approved identification, toolbar customization, window template scrolling and viewport maximization changes.

**Architecture:** Preserve DICOM and workspace identities; derive presentation separately. Persist toolbar preferences through validated settings and keep maximization as window-local UI state. Use shared tool identifiers for all toolbar renderers.

**Tech Stack:** Python, PySide6, Qt Quick/QML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-reading-controls-design.md`

## Global Constraints

- Preserve MPR default layout entry and existing appearance preferences.
- Do not abbreviate original sequence descriptions semantically or change window center/width data semantics.
- No release, tag or remote publication in this task.
- Native GUI actions require visible UI and resulting state checks.

## Review Focus

- Restored and detached tabs must display identities consistent with source metadata.
- Hidden identity must not leak through new labels/tooltips.
- Per-mode sorting must survive capability filtering, locale changes and restart.
- Wheel events at template boundaries must not move the surrounding panel.
- Maximization must not overwrite sidebar preferences or interrupt active image edits.

## Task 1: Identity presentation

Files: workspace/tab presentation models, TabBarSection.qml, Overlay.qml, tests/test_reading_identity.py.
Produces: stable source-derived tab label/tooltip and study date overlay.
- [x] Add behavioral tests for same-patient studies, full descriptions, privacy and restoration; verify failure.
- [x] Implement derived labels without changing tab identities; add overlay date and convert overlay WW/WL order.
- [x] Run identity, workspace and appearance regressions.

## Task 2: Toolbar customization

Files: settings toolbar model/controller, preferences.py, settings QML, LeftPanel.qml, PrimaryToolBar.qml, CompactToolRail.qml, tests/test_toolbar_customization.py.
Produces: validated per-profile groups and ordered tool list for both toolbar forms.
- [x] Add persistence/default/capability tests and UI save/cancel/reorder tests; verify failure.
- [x] Add editor with drag/up/down, pin/unpin, preview, save/cancel/reset.
- [x] Integrate ordering into left/right toolbar renderers; run settings and toolbar regressions.

## Task 3: Window template scrolling and presentation

Files: WindowLevelToolPanel.qml, owning scroll containers, WindowTemplatesPage.qml, related report presentation, tests/test_window_template_scroll.py.
- [x] Add real QML wheel tests checking fixed controls, list boundaries, final applied width/center; verify failure.
- [x] Bound list height to available panel, enable independent scrolling and stop wheel propagation; unify WW then WL.
- [x] Run live windowing, preset, QML layout regressions.

## Task 4: Maximize viewport, copy and integration

Files: Main.qml, CenterPanel.qml, shortcuts.py, languages, help chapters, resources.qrc, tests/test_viewport_maximize.py.
- [x] Add real-window tests for hide/restore, setting preservation, independent windows and mode switches; verify failure.
- [x] Implement window-local maximization with fixed visible toggle and shortcut; rename segmentation import.
- [x] Integrate translations/resources and update manual text.
- [x] Run isolated regression suite and native GUI tests; inspect screenshots and actual state; review final diff.

## Progress

Initial working directory clean at 8d71ec6. Implementation authorized by user; retain current checkout and use a feature branch. Independent tasks will be delegated under dispatching-parallel-agents; shared languages/resources integrated centrally.

- Local branch: codex/reading-controls-20261028.
- Task 4 maximize tests: RED missing action; GREEN 4 offscreen and 4 Cocoa tests. Related window sizing/navigation isolated run: 21 passed. Captured native screenshots inspected.
- Maximize shortcut uses already-reserved F12 rather than introducing a new reserved combination that could invalidate existing custom bindings. Verified again after choosing F12.
- Task 3 expanded by user: star favorites in both preset list/settings, persisted stable IDs, priority order, no window change when starring.
- Tasks 1–3 delegated to reading_identity, toolbar_customization, window_templates. Shared languages and resources integrated by parent; no remote publication.

- Integrated review fixed compact import/export controller wiring and detached-window signal cleanup. Regressions exercise the real chooser route, actual DICOM export files, and notification after QObject deletion.
- Toolbar draft commits merge changed regions/profiles, preserving unrelated newer preferences.
- Compact import labels wrap onto two lines when labels are enabled.
- Compact-tool synchronization waits for final layout. Window preset lists disable asynchronous offscreen delegate caching to avoid disposal during tool switches; tests cover first-tab sizing, playback switches and independent preset scroll extents.

## Final verification

- Full isolated suite plus post-fix/permission reruns: 228 files, 2916 passed, 72 environment/platform-dependent skips, zero outstanding failures/errors. Latest per-file evidence: `build/reading-controls/verified-results.json`.
- Final related rerun: 23 files, 284 passed / 5 skipped. Final native Cocoa interaction batch: 51 passed, including actual compact import route and DICOM export, list scrolling, playback, toolbar settings and viewport maximization. Earlier native identity/detached/privacy and appearance batch: 91 passed. Counts across batches overlap.
- Native screenshots inspected: `build/reading-controls/native-tmp/test_maximize_restores_layout_0/maximized-False.png`, `build/reading-controls/native-captures/labels-compact-dark-zh-CN.png`; identity, toolbar settings and window-list screenshots also inspected. Synthetic data only.
- Independent code review completed. Fixed both concrete issues: compact import/export controller wiring and detached-session signal receiver lifetime. No review blockers remain.
- Manual/resource tests: 23 passed. No version, tag, commit or remote publication performed.
