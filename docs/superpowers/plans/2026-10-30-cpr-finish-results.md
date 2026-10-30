# CPR completion and result layout

Implement the user's requested completion workflow in the current branch. A dedicated Done action, Enter and double-click end path construction/editing through the same dispatcher. Esc cancels the current draft/drag like measurements; committed point moves remain undoable. Switching to another tool cancels unfinished path input. N creates a path and R edits the selected path through the existing configurable, window-scoped shortcut system, with its text-entry/popup/recording guards.

Done opens only curved and cross-section results after a valid current reconstruction is accepted. Editing returns to four reference/result cells; new/cancel and historical measurement navigation must not leave an invisible active viewport. Result cells use a 2:1 horizontal split (stacked below 720 px), while existing viewport controllers preserve navigation, zoom and windowing. Hide path editing controls in result mode, retain position linkage and necessary corner annotations. Store the result-layout choice in CPR session state and accept older sessions without the new field. Combined export follows the visible layout and includes its mode in its revision.

Alternatives: merely changing button labels would leave the user's reported layout problem; a separate results tab would duplicate navigation and state. Reusing the existing cells in one workspace gives an explicit, reversible transition. The user has requested this transition; implement inline without another approval round.

## Tasks

1. Add controller/session tests for finish/edit/new/cancel transitions, pending/failure behavior and legacy session restore. Implement `resultView`, `finishEditing()` and layout-safe activation. Preserve low-level `finishPath()` for committing path geometry.
2. Add configurable `cpr-new`/`cpr-edit` actions (N/R) and verify scope and repeated-key behavior. Route Enter/double-click to the same completion method; retain measurement dispatch.
3. Update CprPage layout and CprPanel actions, tooltips and English/Chinese manual text. Add actual QML pointer/keyboard and image-geometry assertions for result/edit transitions, full-screen restore, narrow layouts and export ownership.
4. Run CPR, shortcut, workspace and export regressions, inspect rendered QML output, obtain independent read-only review, and commit after verification. Native CUA is unavailable in this turn; do not substitute another native UI automation technology.

## Review focus

- Finish while reconstruction is pending/failed must not display a previous path as the new result.
- Hidden reference views cannot remain active after result entry; historical reference recall must reveal its view.
- Editing text and measuring results must not trigger CPR commands or swallow measurement completion.
- Cancelling a new draft returns to the previous result layout without losing the selected path.
- Old workspace files, focused result views and combined export remain coherent across layout changes.

## Completed

Implemented and verified inline. Independent review corrections preserve restored active/maximized views, reveal historical sections, and transfer keyboard focus only when its image becomes hidden. Evidence and test results are in `docs/validation/cpr-results-20261030.md`.
