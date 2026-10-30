# Loading feedback — 2026-10-30

Fast operations no longer immediately display a loading message, spinner or progress bar. QML feedback shares a 300 ms `DelayedActivity` gate; native volume preparation and directory navigation use the same delay. Finishing, cancelling, hiding or changing the feedback context resets the gate. This delays presentation only: input guards, pending state, request identity and cancellation logic still use the actual operation state.

Coverage includes Tag pagination, opening views and tab indicators, CPR reconstruction, MPR references, montage tiles, PET unit changes, PACS queries, import/export, updates, segmentation and workspace save indicators. Tag empty-result text is also hidden during a pending read so it cannot replace a suppressed spinner with a fleeting “no results” message. Errors and completed-operation results remain available immediately. The unfinished-image input blocker remains active from the start.

## Regression checks

The initial affected suite ran 391 cases: 382 passed, 7 skipped and 2 failed (`loading-feedback-20261030/tests.txt`). One failure expected the opening spinner at 100 ms; that test now verifies its absence at 100 ms and subsequent appearance during a sustained wait. The final focused suite covers Tag, view opening, native volume loading and the file picker: 65 passed, 1 skipped, with three existing SWIG deprecation warnings (`final-focused.txt`).

The other failure is an existing offscreen favorites layout issue: `test_inline_favorites_many_resize_manage_and_reload` reports a horizontal scrollbar range of 3 instead of 0. It reproduces in a separate archive of the complete pre-change commit `2069593`, using its own source and tests (`baseline-favorites.txt`). No favorites sizing code was changed here.

New regression assertions first failed before the implementation, then passed after it: quick Tag reads have no status text, delayed reads show feedback, immediate failures show retry/error, completed reads do not inherit stale timers, opening views still block unfinished images, native volume preparation remains responsive, and directory navigation does not show its progress text until needed. A separate read-only review found no blockers and checked that a native-volume failure bypasses the delay and survives late preparation/timer callbacks.

## Native Qt Quick verification

Used the isolated Cocoa validation app with the synthetic 96-instance CT series. Real UI actions navigated pages 1 → 2 → 3 → 4 → 96 → 1. Read-only state-change observations measured approximately 13–36 ms for these page reads, with Tag status, workspace loading message and tab spinners hidden at both request and completion.

- `01-tag-page-96.png` and its JSON snapshot show page 96, filtered Instance Number 96, source `096.dcm`, and SOP instance UID ending in `.96`.
- `02-tag-page-1.png` and its JSON snapshot show page 1, filtered Instance Number 1, source `001.dcm`, and SOP instance UID ending in `.1`. The search term persists across paging.
- The JSON snapshots include the read-only pending/completion visibility trace. The app was returned to the CPR tab after validation.

The separate CPR annotation changes and proposed editing/result layout are documented in `cpr-annotations-20261030.md`; this patch does not implement that layout proposal.
