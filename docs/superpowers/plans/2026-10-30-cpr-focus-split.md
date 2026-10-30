# CPR button focus and adjustable results

The user confirmed N/R and Enter/Esc stop working after clicking the right-hand controls. Reproduce this through real QML button clicks, keeping text-entry, popup, shortcut-recording, non-CPR and window guards. Expose CPR commands at the window shortcut boundary when a non-text control has focus; viewport key handlers continue to own ordinary image input. Repeated edit must preserve the selected reference, and exiting edit from results must return to results. Keep pending completion from briefly presenting ordinary creation/edit controls.

Use the existing WidthResizeHandle and GridLayout, preserving viewport instances. A drag changes a per-CPR-session split ratio; horizontal result cells have a 280-logical-pixel minimum. Keep the existing stacked narrow layout and hide the handle while editing or maximizing one view. Restoring the layout and session retains the chosen ratio. This reuses the application's existing splitter behavior rather than reparenting image items into a second scene.

Implement inline under the user's request: add failing button-focus and splitter tests, implement scoped commands/state and geometry, verify actual pointer/keyboard actions plus visible view sizes and controller state, run relevant regressions, obtain a read-only review, and commit. Native desktop automation tools remain unavailable; distinguish Qt offscreen validation from native testing.

Completed: scoped button/toolbar commands, idempotent edit, prior-layout return, stable pending controls, persisted divider ratio and minimum widths. Regression results and rendered evidence are recorded in `docs/validation/cpr-focus-split-20261030.md`.
