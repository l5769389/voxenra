# CPR fixed action footer — 2026-10-30

The CPR workflow actions now use the existing right-panel footer. New/Edit are shown while viewing results; Done/Cancel while drawing; only Done while editing an existing path. Esc remains available. Point deletion stays beside path controls. The compact flyout reuses the same action component outside its scrolling content.

## Verification

Qt tests ran with `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software` and the repository virtual environment.

- Initial related CPR/input/volume/VOI/MR/toolbar regression: **61 passed** ([log](cpr-footer-20261030/regression.txt)).
- After adding the compact footer: CPR footer, QML, workflow, compact MPR/volume tools, and toolbar customization: **62 passed, 1 skipped** ([log](cpr-footer-20261030/final-ui.txt)). The existing skip is the PET case of a slice/volume window-link test, which uses a different display controller.
- Manual/help validation: **20 passed** ([log](cpr-footer-20261030/manual.txt)).
- Fresh screenshot capture: **2 passed** ([log](cpr-footer-20261030/evidence.txt)).
- `git diff --check` passed. Three existing SWIG deprecation warnings are present; the UI tests assert no QML warnings.

The new tests click actual footer buttons through the main window and compact popup, verify controller mode transitions, check disabled Done before enough control points exist, and ensure the footer stays fixed when expanded parameter content scrolls. Main-window keyboard focus on the relocated buttons still permits Esc and N. Existing workflow tests cover the remaining shortcut behavior. Switching to another tool preserves its reset action.

Independent review found missing compact actions in the initial implementation. The fixed compact footer and its regression were subsequently reviewed and accepted.

## Screenshots

Captured from synthetic test data and visually inspected; these establish Qt layout and interaction behavior, not native macOS or clinical-image validation.

- [Editing with scrolled parameters and one Done action](cpr-footer-20261030/editing-footer.png)
- [Results with New/Edit actions](cpr-footer-20261030/results-footer.png)
- [Collapsed-panel flyout with fixed Done action](cpr-footer-20261030/compact-editing-footer.png)
