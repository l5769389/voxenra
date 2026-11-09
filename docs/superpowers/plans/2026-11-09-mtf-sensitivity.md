# MTF sensitivity presentation implementation plan

**Goal:** Implement the two reviewed discussions: retain computable MTF values, expose processing sensitivity, and separate model estimates, warnings and calculation details.

**Architecture:** Store three comparison samples per measured axis, with a frozen warning threshold per result. A shared presenter derives metric-specific warnings and comparison text without changing numerical values. Workspace records retain measured and modeled results. Per the user's follow-up, image labels contain only geometry, metrics and provenance; warnings remain in the side panel and details.

**Tech stack:** Python/NumPy, PySide6, QML, existing versioned workspace serialization.

**Approved scope:** User asked to implement the linked discussions. Default warning threshold is 20%, adjustable in advanced service settings (1–100%). It is a processing-sensitivity warning, not an uncertainty or acceptance criterion. Saved results change only on explicit recalculation, matching existing analysis preferences.

## Task 1: Preserve measured results

- [x] Add failing tests for sensitive finite results, failed comparisons, missing crossings and threshold independence.
- [x] Store per-axis comparison samples; preserve baseline values/curves on comparison failure. Keep baseline errors.
- [x] Separate routine expansion/multiple-crossing notes from quality warnings.
- [x] Derive Gaussian equivalent sensitivity from measured MTF10 only; keep original measured diagnostics.
- [x] Test old and new workspace serialization.

## Task 2: Settings and presentation

- [x] Add failing controller/QML tests for inline warning, details, frozen threshold, model provenance and workspace roundtrip.
- [x] Add advanced service warning threshold; capture it in each background request and result.
- [x] Present values with metric-specific warning marks, concise warnings and neutral calculation details. Show comparison values in current frequency units.
- [x] Keep warning/threshold information in saved workspace data. The user's follow-up removes warnings from image labels and image exports.
- [x] Update English/Chinese help and release notes.

## Task 3: Verification

- [x] Run affected numeric, controller, QML, settings, workspace tests.
- [x] Recompute the user's three source positions and verify the second/third retain finite sensitive metrics; the first retains genuine computation errors.
- [x] Inspect native rendered results/details/settings in Chinese and English, including narrow panels.
- [x] Review the diff and record the integration contract; defer 2.5.0 release checks until the separate algorithm work is ready.

## Review focus

- Old saved results cannot acquire missing original numbers without recalculation.
- A failed X comparison must not erase a successful Y comparison.
- No-crossing and failed comparison remain distinguishable.
- Gaussian model MTF50 depends on MTF10, not measured MTF50.
- Changing display units scales all comparison values but never the dimensionless sensitivity or recorded threshold.

## Scope update

The user assigned numerical algorithm work to another thread. This implementation changes diagnostics, presentation, persistence and warning policy only. The baseline background estimation, integration support, FFT and first-crossing rules remain unchanged. Do not release until the algorithm changes have been integrated and the combined commit has passed the release checklist.
