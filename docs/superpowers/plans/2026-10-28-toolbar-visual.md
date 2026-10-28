# Toolbar Visual Editing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline.

**Goal:** Edit toolbar order directly on icon buttons using drag and drop.
**Architecture:** QML owns transient pointer/selection state; the existing per-page Python draft controller validates and atomically places stable tool IDs. Persistence and live tool resolution remain unchanged.
**Tech Stack:** PySide6, Qt Quick, pytest/QTest.
**Spec:** docs/superpowers/specs/2026-10-28-toolbar-visual-design.md

## Global Constraints

- Keep seven-item common limit, independent drafts and explicit Save/Cancel.
- No additional dependencies, publication or workspace data changes.
- Keep theme tokens, translated labels and keyboard alternatives.

## Review Focus

- Drops outside a board or canceled drags must not mutate the draft.
- A full common group rejects cross-group insertion without losing a tool.
- Scrolled/empty groups resolve exact insertion position.
- Translated labels and controls remain reachable at minimum window size.
- Draft signals must not delete a live drag source during pointer handling.

## Task 1: Atomic placement and visual editor

Files: toolbar_settings_controller.py, ToolbarSettingsPage.qml, ToolbarOrderList.qml, new ToolbarEditorTile.qml, Voxenra.qrc, translation JSONs, tests/test_toolbar_visual_editor.py, tests/test_toolbar_customization.py.

- [x] Write and run failing tests for `placeEntry(key, source, destination, beforeIndex)`, exact cross-group insertion, no-op and rejected placement.
- [x] Implement the validated atomic draft operation; preserve existing arrow APIs.
- [x] Add real pointer tests for tile reorder, cross-group drag, cancellation and empty-group placement; verify failures before QML implementation.
- [x] Replace text lists/duplicate preview with icon tiles, shared selection actions, drag overlay, insertion marker and edge scrolling.
- [x] Update translations and manual instructions; adapt older layout-dependent tests to select tiles before using shared actions.
- [x] Run focused tests, inspect native screenshots, run the isolated regression suite and obtain an independent code review.

Progress: implementation in the current feature checkout; prior DIMSE merge remains intact. No commit or release requested in this turn.

Completion: independent review findings on narrow layouts and keyboard access were reproduced and fixed. Native verification: 30 passed. Isolated suite with host-permission reruns: 233 files, 2,962 passed, 82 skipped, no failures/errors. See docs/validation/toolbar-visual-editor.md.
