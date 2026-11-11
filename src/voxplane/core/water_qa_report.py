"""Paginated QA PDF from an immutable result and its matching viewport capture."""
from datetime import datetime

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt, QMarginsF
from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout, QPainter, QFont, QColor, QFontMetricsF

from voxplane.i18n import message as _msg
from voxplane.i18n.messages import localize, snapshot
from voxplane.core.measurement_format import format_measurement

METRICS = (("water_ct_hu", "text.1079"), ("noise_hu", "qa.noiseSd"), ("noise_percent", "qa.noisePercent"),
           ("uniformity_hu", "text.1081"), ("consistency_range_hu", "text.1082"),
           ("horizontal_difference_hu", "text.1083"), ("vertical_difference_hu", "text.1084"),
           ("noise_range_hu", "qa.noiseRange"))


def pdf_bytes(result, *, slice_number, spacing, screenshot, software_name="",
              calculated_at="", decimal_places=2, translations=None, report_kind="water"):
    """Never silently create a report without its image or add a default brand."""
    translations = snapshot() if translations is None else translations
    def tr(key):
        return localize(_msg(key), translations)
    def fmt(value):
        return format_measurement(value, decimal_places, missing="—")
    if screenshot is None or screenshot.isNull():
        raise ValueError(tr("qa.reportCaptureFailed"))
    if report_kind not in ("water", "air"):
        raise ValueError("Unknown QA report category")
    air_report = report_kind == "air"
    rois = tuple(r for r in result.rois if (r.group == "air") == air_report)
    if not rois:
        raise ValueError("No ROI in the requested QA report category")
    title = tr("qa.airReportTitle" if air_report else "qa.waterReportTitle")
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(16, 16, 16, 16), QPageLayout.Millimeter)
    writer.setTitle(title)
    writer.setCreator(software_name)
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError(tr("text.0182"))
    for hint in (QPainter.Antialiasing, QPainter.TextAntialiasing, QPainter.SmoothPixmapTransform):
        painter.setRenderHint(hint)
    width, height = writer.width(), writer.height()
    page, y = 0, 0
    bottom = height-90

    def font(size=9, bold=False):
        f = QFont()
        f.setPointSizeF(size)
        f.setBold(bold)
        painter.setFont(f)
        return QFontMetricsF(f, writer)

    def text(value, rect, *, size=9, bold=False, color="#213443", align=Qt.AlignLeft):
        font(size, bold)
        painter.setPen(QColor(color))
        painter.drawText(rect, align | Qt.AlignVCenter | Qt.TextWordWrap, str(value))

    def new_page():
        nonlocal page, y
        if page:
            writer.newPage()
        page += 1
        y = 0
        painter.setPen(QColor("#d5dfe5"))
        painter.drawLine(0, height-72, width, height-72)
        text(software_name, QRectF(0, height-66, width-70, 60), size=8, color="#596f7e")
        text(str(page), QRectF(width-60, height-66, 60, 60), size=8, align=Qt.AlignRight)

    def heading(value, minimum_following=40):
        nonlocal y
        if y+44+minimum_following > bottom:
            new_page()
        text(value, QRectF(0, y, width, 40), size=11, bold=True)
        y += 44

    def table(headers, rows, weights, *, left=0, extent_width=None):
        nonlocal y
        extent_width = width if extent_width is None else extent_width
        widths = [extent_width*w/sum(weights) for w in weights]
        metrics = font()
        flags = Qt.TextWordWrap | Qt.AlignLeft
        def row_height(values):
            return max(34, max(metrics.boundingRect(QRectF(0, 0, w-20, 10000), flags, str(v)).height()+12
                               for v, w in zip(values, widths)))
        header_height = row_height(headers)
        def row(values, extent, header=False, shaded=False):
            nonlocal y
            painter.fillRect(QRectF(left, y, extent_width, extent), QColor("#e9f0f4" if header else "#f5f8fa" if shaded else "white"))
            x = left
            for value, w in zip(values, widths):
                text(value, QRectF(x+10, y+3, w-20, extent-6), bold=header)
                x += w
            painter.setPen(QColor("#d5dfe5"))
            painter.drawLine(round(left), round(y+extent), round(left+extent_width), round(y+extent))
            y += extent
        if y+header_height+(row_height(rows[0]) if rows else 0) > bottom:
            new_page()
        row(headers, header_height, header=True)
        for i, values in enumerate(rows):
            extent = row_height(values)
            if y+extent > bottom:
                new_page()
                row(headers, header_height, header=True)
            row(values, extent, shaded=i % 2 == 1)
        y += 14

    try:
        new_page()
        text(title, QRectF(0, y, width, 60), size=18, bold=True)
        y += 66
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if calculated_at:
            stamp = datetime.fromisoformat(calculated_at).astimezone().strftime("%Y-%m-%d %H:%M")
        text(f"CT · {tr('qa.reportSlice')} {slice_number} · {stamp}", QRectF(0, y, width, 30))
        y += 32
        details = f"{tr('qa.pixelSpacing')}: {fmt(spacing[0])} × {fmt(spacing[1])} mm"
        if result.phantom is not None and not air_report:
            details += f"   ·   {tr('qa.phantomDiameter')}: {fmt(result.phantom.radius_mm*2)} mm"
        text(details, QRectF(0, y, width, 34))
        y += 42
        # Fit the whole screenshot without stretching or cropping its ROI overlays.
        image_height, image_width = 460, width*.49
        section_top = y
        scale = min(image_width/screenshot.width(), image_height/screenshot.height())
        iw, ih = screenshot.width()*scale, screenshot.height()*scale
        painter.drawImage(QRectF((image_width-iw)/2, y, iw, ih), screenshot)
        available = [] if air_report else [
            (tr(label), fmt(getattr(result, key)), "%" if key == "noise_percent" else "HU")
            for key, label in METRICS if getattr(result, key) is not None]
        if air_report and len(rois) == 1:
            available = [(tr('text.0173'), fmt(rois[0].mean_hu), 'HU'),
                         ('SD', fmt(rois[0].std_hu), 'HU')]
        if available:
            left = width*.53
            text(tr('qa.reportSummary'), QRectF(left, y, width-left, 40), size=11, bold=True)
            y += 44
            table([tr('qa.reportMetric'), tr('qa.reportValue'), tr('qa.reportUnit')], available,
                  [2.5, 1.3, .8], left=left, extent_width=width-left)
        y = max(y, section_top+ih)+10
        text(tr("qa.reportImageHint"), QRectF(0, y, width, 32), size=8, color="#596f7e")
        y += 38
        heading(tr('text.1085'), 90)
        table(["ROI", tr('text.0173')+"\nHU", "SD\nHU", tr('text.0174')+"\nHU",
               tr('text.0175')+"\nHU", tr('qa.reportPixels')] + ([] if air_report else ["Δ"+tr('qa.reportCenter')+"\nHU"]),
              [[localize(r.label, translations), fmt(r.mean_hu), fmt(r.std_hu), fmt(r.minimum_hu),
                fmt(r.maximum_hu), str(r.pixel_count)] + ([] if air_report else [fmt(r.delta_center_hu)]) for r in rois],
              [1.3, 1, 1, 1, 1, 1] + ([] if air_report else [1]))
        heading(tr('qa.reportGeometry'), 90)
        table(["ROI / "+tr("qa.reportGroup"), "X\npx", "Y\npx", tr('qa.reportDiameter')+"\nmm", tr('qa.reportArea')+"\nmm²"],
              [[localize(r.label, translations)+" / "+tr({"uniformity":"qa.uniformityGroup", "noise":"qa.noiseGroup", "air":"qa.airTab"}[r.group]), fmt(r.column), fmt(r.row), fmt(r.radius_mm*2),
                fmt(r.area_mm2)] for r in rois], [2.3, 1, 1, 1, 1.5])
        if y+54 > bottom:
            new_page()
        text(tr('qa.reportFootnote'), QRectF(0, y, width, 54), size=8, color="#596f7e")
    finally:
        painter.end()
    data = bytes(buffer.data())
    buffer.close()
    return data
