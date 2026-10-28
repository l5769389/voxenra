# Traditional DICOM Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Traditional PACS query/download without C-GET, on an independent branch, verified with OrbStack.
**Architecture:** Protocol profiles and factory reuse controller/importer. DIMSE owns associations and a temporary validated receiver.
**Tech Stack:** Python/pydicom/pynetdicom, PySide6/QML, OrbStack/Compose.
**Spec:** docs/superpowers/specs/2026-10-28-dicom-dimse-design.md

## Global Constraints
No C-GET, upload UI, persistent unsolicited receiver, release or other-checkout changes. Preserve DICOMweb. Synthetic lab data only.

## Review Focus
Cancellation during blocked I/O; success with missing objects; unrelated/concurrent C-STORE; old profile migration and session secrets; server failure masquerading as empty query.

### Task 1: Profiles and boundary
Files: pacs/config.py, pacs/transport.py, ui/controller/pacs_controller.py; tests/test_dimse_config.py.
Interface: PacsProfile.protocol and connection fields; create_client(profile, cancel).
- [ ] Write/run failing validation/migration/protocol switching tests.
- [ ] Implement profile and factory/controller dispatch.
- [ ] Run new and existing PACS tests, commit.

### Task 2: Network and atomic import
Files: pacs/dimse_client.py, pacs/dimse_receiver.py, pacs/importer.py, pyproject.toml/uv.lock; tests/test_dimse.py.
Interface: test_connection(), studies(filters,offset,limit), series(study,offset,limit), retrieve_series(selections,folder,progress).
- [ ] Real loopback ECHO/FIND/MOVE tests: identity/pixels, rejection, missing/wrong objects, duplicates, cancel, port collision and failures; run RED.
- [ ] Implement finite association/listener lifecycle, query normalization, receiver validation and atomic import; run GREEN.
- [ ] Run network and existing import regressions; commit.

### Task 3: Configuration and visible workflow
Files: PacsProfileDialog.qml, DataSourcesPage.qml, PacsBrowser.qml, languages; tests/test_dimse_qml.py.
Interface: existing saveProfile/testDraft/queryStudies/importSelected slots.
- [ ] Failing real QML protocol/validation/persistence/test-feedback/query-to-import tests.
- [ ] Add protocol-specific fields, endpoint labels and C-MOVE setup guidance; verify small-window reachability.
- [ ] Run QML/theme/i18n/PACS tests; commit.

### Task 4: OrbStack and delivery
Files: docker/pacs-dimse/*, tests/manual/dimse_lab.py, tests/test_dimse_live.py, docs/pacs.md, docs/pacs-lab.md, docs/validation/dicom-dimse.md.
- [ ] Dedicated Orthanc/dcm4chee lab, explicit AEs and Mac return endpoint.
- [ ] Real ECHO/FIND/MOVE, UID/pixel identity, repeat imports, failure/recovery and native GUI/state verification.
- [ ] Document actual results; full isolated regression and fresh review; fix significant findings.
- [ ] Commit independent branch; leave reviewable worktree and report boundaries.
