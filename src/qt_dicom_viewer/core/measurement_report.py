"""Data-only measurement export; formatted values never replace source statistics."""
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import localize, snapshot
import csv
from datetime import datetime
import io
import math
from qt_dicom_viewer.core.measurement_format import DEFAULT_DECIMAL_PLACES, format_measurement

COLUMNS = (
    ("patient", _msg('text.0159')), ("patient_id", _msg('text.0029')), ("series", _msg('text.0160')),
    ("modality", _msg('text.0026')), ("view", _msg('text.0161')), ("slice", _msg('text.0162')),
    ("phase", _msg('text.0163')), ("id", _msg('text.0164')), ("kind", _msg('text.0165')),
    ("length_mm", _msg('text.0166')), ("angle_deg", _msg('text.0167')),
    ("width_mm", _msg('text.0168')), ("height_mm", _msg('text.0169')), ("area_mm2", _msg('text.0170')),
    ("volume_cm3", _msg('text.0171')), ("pixel_count", _msg('text.0172')),
    ("mean", _msg('text.0173')), ("std", "SD"), ("minimum", _msg('text.0174')), ("maximum", _msg('text.0175')),
    ("unit", _msg('text.0176')), ("threshold", _msg('text.0177')),
    ("origin", _msg('text.0178')), ("orientation", _msg('text.0179')), ("text", _msg('text.0180')),
    ("perimeter_mm", _msg("measurement.perimeter")),
    ("name", _msg("results.rename")),
    ("reference_status", _msg("report.referenceStatus")),
)


MEASUREMENT_COLUMNS = frozenset({"length_mm", "angle_deg", "width_mm", "height_mm", "area_mm2",
                                 "perimeter_mm", "volume_cm3", "mean", "std", "minimum", "maximum", "threshold"})


def cell(value, *, decimal_places=None):
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and decimal_places is not None:
        return format_measurement(value, decimal_places, missing="")
    if isinstance(value, float):
        return format(value, ".10g")
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def csv_bytes(rows, *, translations=None, decimal_places=DEFAULT_DECIMAL_PLACES):
    translations = snapshot() if translations is None else translations
    rows = localize(rows, translations)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([localize(label, translations) for _, label in COLUMNS])
    for row in rows:
        writer.writerow([cell(row.get(key), decimal_places=decimal_places if key in MEASUREMENT_COLUMNS else None) for key, _ in COLUMNS])
    return output.getvalue().encode("utf-8-sig")


def pdf_bytes(rows, *, anonymous=True, images=(), created=None, translations=None, decimal_places=DEFAULT_DECIMAL_PLACES):
    """Use the Qt runtime already shipped with Voxenra; no extra packaging cost."""
    translations = snapshot() if translations is None else translations
    rows = localize(rows, translations)
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt, QMarginsF
    from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout, QPainter, QFont, QColor, QFontMetricsF
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(16, 16, 16, 16), QPageLayout.Millimeter)
    writer.setTitle(localize(_msg('text.0181'), translations))
    writer.setCreator("Voxenra")
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError(_msg('text.0182'))
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    width, height = writer.width(), writer.height()
    page, y = 0, 0
    stamp = created or datetime.now().strftime("%Y-%m-%d %H:%M")

    def text(value, x, yy, w, h, size=10, bold=False, color="#213443", single=False):
        value = localize(value, translations)
        font = QFont()
        font.setPointSizeF(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        value = QFontMetricsF(font, writer).elidedText(str(value), Qt.ElideRight, w) if single else str(value)
        painter.drawText(QRectF(x, yy, w, h), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, value)

    def new_page():
        nonlocal page, y
        if page:
            writer.newPage()
        page += 1
        text(_msg('text.0183'), 0, 0, width, 46, 17, True)
        text(_msg('text.0184', value1=stamp, value2=_msg('text.0185') if anonymous else _msg('text.0186'), value3=len(rows)),
             0, 50, width, 35, 9, color="#596f7e")
        painter.setPen(QColor("#c8d4db"))
        painter.drawLine(0, 96, width, 96)
        text(f"Voxenra  ·  {page}", 0, height - 28, width, 28, 9, color="#596f7e")
        y = 116

    try:
        new_page()
        for row in rows:
            metrics = [(localize(label, translations), cell(row.get(key), decimal_places=decimal_places if key in MEASUREMENT_COLUMNS else None)) for key, label in (*COLUMNS[9:22], COLUMNS[-3])
                       if row.get(key) is not None and row.get(key) != ""]
            lines = ["  ·  ".join(f"{label}: {value}" for label, value in metrics[i:i+2])
                     for i in range(0, len(metrics), 2)]
            if row.get("reference_status"):
                lines.append(row["reference_status"])
            if row.get("text"):
                lines.append(_msg('text.0187') + row["text"][:180])
            block = 96 + len(lines) * 34
            if y + block > height - 55:
                new_page()
            painter.fillRect(QRectF(0, y, width, 40), QColor("#edf3f6"))
            text(f"{row['id']}  {row.get('name') or row['kind']}  ·  {row['patient']} / {row['series']}",
                 12, y, width-24, 40, 10, True, single=True)
            location = f"{row['modality']} · {row['view']}"
            if row.get("slice"): location += _msg('text.0188', value1=row['slice'])
            if row.get("phase"): location += _msg('text.0189', value1=row['phase'])
            text(location, 12, y + 44, width - 24, 34, 9, color="#596f7e")
            for i, line in enumerate(lines):
                text(line, 12, y + 78 + i * 34, width - 24, 34, 10, single=True)
            y += block + 14
        if not rows:
            text(_msg('text.0190'), 0, y, width, 40)
        for caption, image in images:
            new_page()
            text(caption, 0, y, width, 64, 11, True, single=True)
            y += 80
            target = image.size().scaled(int(width), int(height-y-70), Qt.KeepAspectRatio)
            painter.drawImage(QRectF((width-target.width())/2, y, target.width(), target.height()), image)
            text(_msg('text.0191'), 0, height-64, width, 30, 9)
    finally:
        painter.end()
    result = bytes(buffer.data())
    buffer.close()
    return result
