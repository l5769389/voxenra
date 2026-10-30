# CPR fixed footer actions

Move New/Edit/Done/Cancel into the existing ToolResetBar, beside the collapse control and outside the scrolling parameters. Use its ToolActionButton style. Empty/result mode offers New (and Edit when a path exists); drawing offers Done/Cancel; editing offers only Done. Keep Delete point with path controls. Old four-pane review sessions offer Edit/Done. Keep Esc as an editing shortcut, without a second exit button.

Reuse controller actions and IDs, update shortcut ancestry for the new footer, and keep other tools' bottom actions unchanged. Verify actual main-window clicks, keyboard focus, scrolling with expanded content, visibility by mode, and existing CPR/right-panel regressions. Implement inline as requested; no reconstruction or persistence changes.

Completed. The compact panel flyout also reuses the fixed actions outside its scrolling parameters. Expanded and compact click flows, scrolling, keyboard focus, related tool panels, and help checks passed; see [validation](../../validation/cpr-footer-20261030.md).
