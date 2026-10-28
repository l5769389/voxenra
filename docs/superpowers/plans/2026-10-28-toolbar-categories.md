# Toolbar categories implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline.

**Goal:** Six clear toolbar settings categories with preserved detailed configurations.
**Architecture:** Add presentation-only grouping to the draft editor; obtain initial profile from the owning window's most recent image tab. Keep existing persistence and runtime resolver.
**Tech Stack:** Python, PySide6, QML.
**Spec:** `docs/superpowers/specs/2026-10-28-toolbar-categories-design.md`

## Global Constraints

- Preserve all stored profile keys and existing uncommitted work.
- No release, push, or commit requested.
- Six categories, collapsed details, always-visible exact profile.

## Review Focus

- Comparison/PET-CT configurations remain reachable without mutating neighbors.
- Invalid options cannot select a nonexistent profile.
- Context comes from the owning window; utilities do not erase it.
- Locale changes update labels without resetting selection/drafts.
- Expanded details fit small windows and keyboard traversal.

### Task 1: Grouping, context, and UI

**Files:** toolbar_settings_controller.py, tool_controller.py, window_workspace_controller.py; ToolbarSettingsPage.qml, SettingsPage.qml, CenterPanel.qml; language JSON, docs/manual.md; toolbar tests.
**Interfaces:** editor viewCategories/selectedCategory, modes/selectedMode, capabilities/selectedCapability, selectedProfileLabel; selectCategory/selectMode/selectCapability. ToolController.toolbarProfile; WindowWorkspaceController.toolbarProfileForEditing().

- [x] Add behavioral tests for independent profiles, context, and UI controls; run to confirm missing-feature failure.
- [x] Implement grouping and context selection without changing persisted data.
- [x] Replace flattened selector with category and collapsible details; update translations/manual.
- [x] Run related isolated tests and native UI checks, inspect screenshots, check diff.
- [x] Review final changes and document evidence.

## Execution notes

- Initial RED: 9 failures on missing grouping/context interfaces and the old 26-item selector.
- Keep the existing settings-page lifetime: leaving the page destroys its draft editor. The context test instead verifies that activity in a second real window cannot reset a live editor in the first.
- Keyboard reverse traversal initially skipped expanded detail controls; an interaction regression failed before fixing `focusBeforeGroup`.
- Final native macOS category tests: 11 passed, with screenshots for three languages and 800×600 expanded settings. Independent review found no remaining actionable issues. Full isolated regression: 234 files, 2976 passed, 82 skipped, 0 failures/errors. See `docs/validation/toolbar-categories.md`.
