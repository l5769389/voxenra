# Display and export presets implementation plan

> **For agentic workers:** Use scoped parallel implementation for independent display, capture and report domains; root integrates shared settings and reviews the whole change.

**Goal:** User-configurable new-view defaults and reusable screenshot/report export presets.
**Architecture:** Validated preferences feed only new-view construction; frozen capture/report jobs consume copied options. Report preview and save share PDF bytes.
**Tech Stack:** Python, PySide6, QtQuick, existing PDF and DICOM paths. No new dependencies.
**Spec:** docs/superpowers/specs/2026-11-12-display-export-presets-design.md

## Global constraints
Preserve dirty baseline, saved workspace format, quantitative calculations, privacy checks, existing cancellation/atomic writes. No release or version change. User authorized implementation of the proposed scope in a new branch.

## Review focus
- Invalid or removed presets fall back without breaking loading.
- Restored tabs keep old values despite new global preferences.
- Capture restores flags on cancellation/error and cannot mix changing sources.
- Preview remains identical to saved report after editing source.
- Empty metrics, patient boundaries, large tables and Unicode are handled explicitly.

## Tasks
- [x] 1. Root: validated preset persistence/defaults and settings integration; tests invalid sizes/enums/text, roundtrip, drafts vs saves. Files settings/preferences.py, settings/export_presets.py, controller/settings_controller.py; tests/test_export_presets.py.
- [x] 2. Display defaults: construction-only application to2D/MPR, settings page and isolated tests of window rule/zoom/restoration. New settings/display_defaults.py and QML InitialDisplaySettings.qml; integrate viewport construction.
- [x] 3. Screenshot options: capture current/all viewport, PNG/JPEG and sizes/layers, settings panel and tests for dimensions/pixels/revision/cancellation. ExportController, ExportPanel and QML capture layers.
- [x] 4. Reports: shared style/options, measurement/QA generators and frozen PDF preview/save dialog, result selection and metadata; numeric/content/pagination/preview consistency tests. New core/report_options.py, ui/controller/report_preview_controller.py and report QML components.
- [x] 5. Root: integrate translations/help/default settings, inspect UI+result state, scoped regression, full isolated regression, independent review, record final changes/tests. Preserve unrelated work; commit only scoped changes if separable, otherwise leave reviewed branch worktree without bundling unrelated baseline.

For each task: add meaningful failing tests, observe failure, implement, rerun focused tests. Record decisions and outcomes below.

## Ledger
- Branch codex/display-export-presets created with existing dirty work preserved.
- Existing fixed A4 PDF exporters and viewport PNG capture are reused. Report API remains backward-compatible through optional keyword options.

- Shared defaults and named presets validated atomically; legacy report credit migrates with an explicit new value taking precedence. Per-report identity/content is rejected from presets.
- Initial 2D/MPR defaults verified against new view creation, initial layout, disabled template fallback, workspace restore and undo-close.
- Screenshot export verified for PNG/JPEG, aspect-preserving size, metadata removal, frozen-source checks and recursive layer restoration. Native Cocoa/VTK capture checks active and whole-tab output including direction-marker suppression/restoration on render failure.
- Reports support current tab/current study/checked results, frozen preview/save, long Unicode pagination, role labels, source-filtered privacy checks, and category-specific QA filenames.
- Settings/report dialogs exercised in three themes and narrow/wide layouts. Updated Chinese/English tutorial sections preserve existing message IDs and chapter anchors; added settings search terms.
- Full isolated run covered 310 files. Four initial navigation failures were investigated: duplicate category header removed; keyboard traversal test now includes the new category. All failed/affected files rerun successfully. Final evidence and environment skips are recorded in docs/validation/display-export-presets-20261112.md.
- No commit/release: pre-existing uncommitted changes overlap shared files; preserve the complete reviewed worktree on the requested branch without bundling unrelated baseline work into a commit.
