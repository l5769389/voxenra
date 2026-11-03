"""Choose comparison series without duplicating catalog state."""
from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.core.compare import supports_compare, supports_mpr_compare
from qt_dicom_viewer.core.series_sidebar import series_sort_key


class CompareSeriesController(QObject):
    changed = Signal()
    openRequested = Signal(str, str)
    mprOpenRequested = Signal(str, str)
    multiOpenRequested = Signal(object)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self._anchor = self._partner = ""
        self._partners = []
        self._open = False
        self._mode = "2d"
        panel.seriesItemsChanged.connect(self._catalog_changed)

    def _record(self, uid):
        return self.panel._scan_series_record.get(uid)

    def _item(self, record):
        return dict(seriesUid=record.series_instance_uid, patientName=record.patient_name,
                    patientId=record.patient_id, studyDate=record.study_date,
                    description=record.series_description or record.modality,
                    modality=record.modality, count=len(record.instances))

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    def _supports(self, record):
        return (supports_mpr_compare if self._mode == "mpr" else supports_compare)(record)

    @Property(bool, notify=changed)
    def dialogOpen(self):
        return self._open

    @Property('QVariantMap', notify=changed)
    def anchor(self):
        record = self._record(self._anchor)
        return self._item(record) if record else {}

    @Property('QVariantList', notify=changed)
    def candidates(self):
        anchor = self._record(self._anchor)
        records = [record for record in self.panel._scan_series_record.values()
                   if record.series_instance_uid != self._anchor and self._supports(record)]
        records.sort(key=lambda record: (not (anchor and self.panel._same_patient(anchor, record)),
                                        record.patient_name, record.study_date, series_sort_key(record)))
        return [self._item(record) for record in records]

    @Property(str, notify=changed)
    def partnerUid(self):
        return self._partner

    @Property(bool, notify=changed)
    def canConfirm(self):
        limit = 1 if self._mode == "mpr" else 3
        return 1 <= len(self._partners) <= limit and self._anchor not in self._partners and all(
            self._supports(self._record(uid)) for uid in (self._anchor, *self._partners))

    @Slot(str, result=bool)
    def supportsSeries(self, uid):
        return supports_compare(self._record(uid))

    @Slot(str, result=bool)
    def supportsMprSeries(self, uid):
        return supports_mpr_compare(self._record(uid))

    @Slot(QObject)
    def requestFromViewport(self, viewport):
        selected = [uid for uid in self.panel.selectedSeriesUids if self.supportsSeries(uid)]
        config = getattr(viewport, "viewport_config", None)
        context_uid = (self.panel.activeSeriesUid if self.panel.activeSeriesUid in selected else selected[0]) if selected else (
            config.series_uid if config is not None else self.panel.activeSeriesUid)
        self.request(context_uid)

    @Slot(str)
    def request(self, context_uid):
        self._request(context_uid, "2d")

    @Slot(str)
    def requestMpr(self, context_uid):
        self._request(context_uid, "mpr")

    def _open_selection(self, selected):
        if self._mode == "mpr":
            self.mprOpenRequested.emit(*selected)
        elif len(selected) == 2:
            self.openRequested.emit(*selected)
        else:
            self.multiOpenRequested.emit(selected)

    def _request(self, context_uid, mode):
        self._mode = mode
        if not self._supports(self._record(context_uid)):
            return
        selected = self.panel.selectedSeriesUids
        allowed_counts = (2,) if mode == "mpr" else (2, 3, 4)
        if len(selected) in allowed_counts and context_uid in selected and all(self._supports(self._record(uid)) for uid in selected):
            self._open_selection(selected)
            return
        self._anchor, self._partner = context_uid, ""
        self._partners = []
        self._open = True
        self.changed.emit()

    @Slot(str)
    def selectPartner(self, uid):
        if uid != self._anchor and self._supports(self._record(uid)):
            self._partner = uid
            self._partners = [uid]
            self.changed.emit()

    @Property('QVariantList', notify=changed)
    def partnerUids(self):
        return list(self._partners)

    @Slot(str)
    def togglePartner(self, uid):
        if uid == self._anchor or not self._supports(self._record(uid)): return
        if uid in self._partners: self._partners.remove(uid)
        elif self._mode == "mpr": self._partners = [uid]
        elif len(self._partners) < 3: self._partners.append(uid)
        self._partner = self._partners[0] if self._partners else ""
        self.changed.emit()

    @Slot()
    def confirm(self):
        if self.canConfirm:
            self._open = False
            self._open_selection([self._anchor, *self._partners])
            self.changed.emit()

    @Slot()
    def cancel(self):
        if self._open:
            self._open = False
            self._partner = ""
            self._partners = []
            self.changed.emit()

    @Slot()
    def _catalog_changed(self):
        self._partners = [uid for uid in self._partners if self._supports(self._record(uid))]
        if not self._supports(self._record(self._anchor)):
            self._open = False
        self._partner = self._partners[0] if self._partners else ""
        self.changed.emit()
