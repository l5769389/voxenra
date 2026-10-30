# CPR button focus and result splitter — 2026-10-30

The reported shortcut failure reproduced after an actual click on the CPR advanced-settings button: N/R were excluded by Main's blanket button-focus guard, and Enter/Escape were handled only by viewport Keys handlers. CPR commands now retain the window's text, popup, recording and document-operation guards, but can run from CPR action buttons. Ordinary image input and other tools retain their existing key ownership. Toolbar buttons use TabFocus rather than taking focus on mouse clicks; their keyboard-focus route is covered separately.

Repeated Edit no longer resets the active reference to reference A. Exiting an edit started from results returns to the results layout, preserving committed point changes. New remains available during editing, repeated New preserves the draft, and pending completion does not briefly expose ordinary New/Edit controls. The panel and fixed shortcuts use the same completion/cancellation availability properties.

The results divider reuses WidthResizeHandle with an 8-pixel drag target and horizontal-resize cursor. Both viewport cells stop at 280 logical pixels (276 image pixels inside their borders). The chosen ratio is kept per CPR session, survives editing/maximizing/narrow-layout transitions, and is saved in workspace files. Older sessions default to 2:1. Windows narrower than 720 pixels retain the stacked result layout. Export revision tracking includes the ratio.

## Verification

All runs used `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/pytest`.

- Initial regressions: the four button-focus commands, repeated Edit and missing divider all failed before implementation.
- Related CPR, input, navigation, settings, manual and anonymous-export suite: **217 passed** (`cpr-focus-split-20261030/related-tests.txt`).
- Final button/toolbar focus, remapped N, text/modal guards, point deletion, splitter and shared-input suite: **24 passed** (`final-input-tests.txt`).
- Persistence and manual checks, including saving/restoring a 0.58 split ratio with historical reference data: **29 passed** (`persistence-manual-tests.txt`).
- Rendered splitter verification with an intensity-ramp phantom: **1 passed** (`split-visual-test.txt`). The three PNGs show adjusted widths and each minimum-width boundary. Tests verify real pointer drags, visible geometry, cursor and controller/session state.

Three pre-existing SWIG deprecation warnings remain. QML warnings were checked and none were accepted. A read-only reviewer found no actionable issues and additionally checked keypad Enter, shortcut recording Escape, ComboBox popup Escape, and inactive-CPR isolation from 2D controls.

This is Qt offscreen integration/render validation. Native desktop automation was unavailable and no claim is made about a new native macOS run. Reconstruction mathematics were unchanged.
