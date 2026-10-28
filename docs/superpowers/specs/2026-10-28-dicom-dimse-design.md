# Traditional DICOM PACS

User requested an independent branch with traditional DICOM support, excluding C-GET, verified with real PACS on OrbStack. Implement C-ECHO, Study Root C-FIND (STUDY/SERIES/IMAGE), series C-MOVE and temporary C-STORE reception. Preserve DICOMweb and the other checkout.

Use pynetdicom inside the existing Python app, sharing the PACS controller, normalized rows and scanner/catalog import path. A gateway adds deployment burden; DCMTK subprocesses add platform binaries. Native transport is the selected implementation judgment under the user's instruction to proceed.

Profiles add protocol, host/port, called AE, calling/receiving AE, receiver bind address/port and timeout. Old profiles remain DICOMweb. No upload UI, C-GET, unsolicited permanent receiver or release. New fields and errors use existing language infrastructure.

Query results must be complete, bounded and stably sorted before client paging. Reject failures/truncation/malformed identifiers. C-ECHO proves association only, not query permissions or the reverse C-MOVE connection. UI explains PACS registration of the local AE and reachable port.

During import, start a temporary Storage SCP, validate peer AE and Study/Series/SOP identity against an IMAGE-level query manifest, stage files and verify final success and every expected instance before scanner/catalog publication. Reject unrelated and conflicting objects. Preserve valid transfer syntax metadata. Cancellation/failure closes associations/listener and removes partial files. All networking runs in workers with bounded timeouts and actionable errors.

Verification: existing PACS baseline, real local protocol peers with failure injection, actual QML configure/query/import tests, dedicated Orthanc and dcm4chee OrbStack lab using synthetic data, independent UID/pixel identity checks, native rendered 2D and controller state, full isolated regression and final fresh branch review. Hospital-specific interoperability and Windows runtime cannot be established solely by local macOS tests.
