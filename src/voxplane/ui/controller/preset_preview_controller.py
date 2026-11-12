"""Patient-independent, live examples for display and export preferences."""
import base64
import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QBuffer, QIODevice, QSize, Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QFont, QFontMetricsF, QGuiApplication
from PySide6.QtPdf import QPdfDocument
from voxplane.i18n import message as _msg
from voxplane.i18n.messages import localize


def image_url(image, format='PNG', quality=-1):
    buffer = QBuffer(); buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, format, quality):
        raise ValueError('Preview image encoding failed')
    mime = 'jpeg' if format == 'JPEG' else 'png'
    return 'data:image/'+mime+';base64,'+base64.b64encode(bytes(buffer.data())).decode('ascii')


def phantom(width=350, center=40, modality='CT'):
    y, x = np.mgrid[-1:1:512j, -1:1:512j]
    radius = x*x+y*y
    pixels = np.full(x.shape, -1000. if modality == 'CT' else 0.)
    pixels[radius < .72] = 20 if modality == 'CT' else 280
    pixels[radius < .58] = 40 if modality == 'CT' else 420
    for cx, cy, value in [(-.35,-.25,-120),(.35,-.25,150),(-.35,.3,550),(.35,.3,0)]:
        pixels[(x-cx)**2+(y-cy)**2 < .026] = value if modality == 'CT' else abs(value)+100
    pixels += np.where(radius < .58, 15*np.sin(x*34)*np.cos(y*28), 0)
    values = np.clip((pixels-(center-width/2))/max(1,width)*255,0,255).astype(np.uint8)
    return QImage(values.data,512,512,512,QImage.Format_Grayscale8).copy()


def example_corner_rows(modality, window, options, *, hide_identity=False, zoom="fit"):
    """Use the viewer's English field labels and configured corner order."""
    fields = dict(viewPosition='Axial · S: 25.00 mm', manufacturer='Example',
                  seriesDescription=modality+' QA phantom · DEMO', studyDescription='QA DEMO',
                  modality=modality, slice='Slice: 26 / 100', patientName='Patient: DEMO',
                  patientId='ID: DEMO-001', studyDate='Study date: 2026/01/01',
                  exposure='TR: 500 ms   TE: 15 ms' if modality=='MR' else 'kV: 120   mA: 100',
                  sliceThickness='Thickness: 1.0 mm', window=f'WW: {window[0]:g}   WL: {window[1]:g}',
                  transform='Rot: 0° · Flip: —', cursor='X: —   Y: —\n'+('Value: —' if modality=='MR' else 'CT: — HU'),
                  zoom=f"Zoom: {example_geometry(zoom)['size']/512*100:.0f}%", instanceNumber='Instance: 26', matrix='512 × 512',
                  spacing='Spacing: 0.5 × 0.5 mm', seriesUid='DEMO')
    if hide_identity:
        for key in ('patientName','patientId','studyDate'): fields[key]=''
    return {corner:[line for key in options[corner] for line in fields.get(key,'').splitlines() if line]
            for corner in ('topLeft','topRight','bottomLeft','bottomRight')}


def example_geometry(zoom='fit'):
    # A 512×512 synthetic image at 0.5 mm/pixel: geometry and scale share units.
    size=360 if zoom=='fit' else 512
    pixels_per_mm=size/(512*.5)
    return dict(size=size, pixelsPerMm=pixels_per_mm, roiDiameter=25*pixels_per_mm,
                lineLength=38.4*pixels_per_mm, scaleLength=50*pixels_per_mm)


def example_image(*, layers=None, zoom='fit', window=(350,40), modality='CT',
                  corner_options=None, measurement_kind='roi'):
    from voxplane.settings.preferences import DEFAULTS
    layers = layers or {}
    corners = corner_options or DEFAULTS['corners']
    image=QImage(1200,720,QImage.Format_RGB32);image.fill(QColor('#080d12'))
    painter=QPainter(image);painter.scale(2,2)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.TextAntialiasing)
    geometry=example_geometry(zoom);size=geometry['size']
    painter.drawImage(QRectF((600-size)/2,(360-size)/2,size,size),phantom(*window,modality))
    font=QFont(QGuiApplication.font());font.setPixelSize(corners['fontSize'])
    font.setLetterSpacing(QFont.AbsoluteSpacing,0);font.setWordSpacing(0);font.setWeight(QFont.DemiBold)
    painter.setFont(font)
    color=QColor(corners['color'] if corners['colorMode']=='custom' else '#edf5fa')
    painter.setPen(color)
    if layers.get('parameters',True) and corners['enabled'] and not layers.get('anonymous',False):
        rows=example_corner_rows(modality,window,corners,hide_identity=layers.get('hideIdentity',False),zoom=zoom)
        row_height=corners['fontSize']*corners['lineHeight']
        limit=max(0,min(12,int((180-24)/row_height)))
        metrics=QFontMetricsF(font)
        for corner,lines in rows.items():
            lines=lines[:limit]
            right=corner.endswith('Right');bottom=corner.startswith('bottom')
            x=312 if right else 12
            y=348-len(lines)*row_height if bottom else 12
            for index,line in enumerate(lines):
                line=metrics.elidedText(line,Qt.ElideRight,276)
                painter.drawText(QRectF(x,y+index*row_height,276,row_height),
                                 (Qt.AlignRight if right else Qt.AlignLeft)|Qt.AlignVCenter,line)
    if layers.get('directions',True):
        painter.setPen(QColor('#edf5fa'))
        for label,rect in [('A',QRectF(285,8,30,20)),('P',QRectF(285,332,30,20)),
                           ('R',QRectF(8,170,20,20)),('L',QRectF(572,170,20,20))]:
            painter.drawText(rect,Qt.AlignCenter,label)
    if layers.get('measurements',True):
        painter.setPen(QPen(QColor('#ffd45c'),1.5))
        if measurement_kind=='length':
            half=geometry['lineLength']/2
            painter.drawLine(QRectF(300-half,180,2*half,0).topLeft(),QRectF(300-half,180,2*half,0).bottomRight())
            label='M002 · 38.4 mm'
        else:
            diameter=geometry['roiDiameter']
            painter.drawEllipse(QRectF(300-diameter/2,180-diameter/2,diameter,diameter))
            label='M001 · Ø 25.0 mm'
        painter.drawText(QRectF(330,150,200,24),Qt.AlignLeft|Qt.AlignVCenter,label)
    if layers.get('scale',True):
        half=geometry['scaleLength']/2
        painter.setPen(QPen(QColor('#edf5fa'),1.5))
        painter.drawLine(QRectF(300-half,298,2*half,0).topLeft(),QRectF(300-half,298,2*half,0).bottomRight())
        for x in (300-half,300+half):painter.drawLine(QRectF(x,295,0,6).topLeft(),QRectF(x,295,0,6).bottomRight())
        painter.drawText(QRectF(265,276,70,20),Qt.AlignCenter,'50 mm')
    painter.end()
    return image


class PresetPreviewController(QObject):
    changed=Signal()
    def __init__(self, settings, kind, parent=None):
        super().__init__(parent)
        if kind not in ('initialDisplay','screenshot','report'): raise ValueError(kind)
        self.settings,self.kind=settings,kind
        self._pages=[];self._caption='';self._error='';self._modality='CT'
        self._timer=QTimer(self);self._timer.setSingleShot(True);self._timer.setInterval(160)
        self._timer.timeout.connect(self.refresh)
        settings.sectionChanged.connect(self._section_changed)
        self._timer.start(0)

    def _section_changed(self,section):
        if section in (self.kind,'window','appearance','corners','privacy') or (section=='export' and self.kind in ('screenshot','report')):
            self._timer.start()

    @Property('QStringList',notify=changed)
    def pages(self): return self._pages
    @Property(str,notify=changed)
    def caption(self): return self._caption
    @Property(str,notify=changed)
    def error(self): return self._error
    @Slot(str)
    def setModality(self,value):
        if value in ('CT','MR') and value!=self._modality:
            self._modality=value;self._timer.start()

    @Slot()
    def refresh(self):
        self._timer.stop()
        try:
            options=self.settings.section(self.kind)
            if self.kind=='report':
                self._report(options)
            elif self.kind=='initialDisplay':
                window=(350,40) if self._modality=='CT' else (800,400)
                if options['windowMode']=='preset':
                    entry=next((e for e in self.settings.windowTemplates if e['presetId']==options[self._modality.lower()+'Preset'] and e['enabled']),None)
                    if entry: window=(entry['width'],entry['center'])
                self._pages=[image_url(example_image(zoom=options['zoom'],window=window,modality=self._modality,layers={'measurements':False,'hideIdentity':self.settings.section('privacy')['hideIdentity']},corner_options=self.settings.section('corners')))]
                self._caption=f'{self._modality} · WW {window[0]:g} / WL {window[1]:g} · '+localize(_msg('initialDisplay.'+('pixel' if options['zoom']=='pixel' else 'fit')))
            else:
                image=example_image(layers={**options,'hideIdentity':self.settings.section('privacy')['hideIdentity']},corner_options=self.settings.section('corners'))
                if options['scope']=='tab':
                    tile=QImage(1200,720,QImage.Format_RGB32);tile.fill(QColor('#080d12'))
                    painter=QPainter(tile);painter.scale(2,2)
                    for x,y in [(0,0),(302,0),(0,182),(302,182)]:
                        painter.drawImage(QRectF(x,y,298,178),image)
                    painter.end();image=tile
                width,height=image.width(),image.height()
                if options['size']=='longEdge':
                    width=options['longEdge'];height=round(width*image.height()/image.width())
                self._pages=[image_url(image,options['format'].upper(),options['jpegQuality'])]
                dimensions = localize(_msg("screenshot.current")) if options["size"]=="current" else f"{width} × {height} px"
                self._caption=f"{options['format'].upper()} · {dimensions} · {options['filenamePrefix']}."+('jpg' if options['format']=='jpeg' else 'png')
            self._error=''
        except Exception:
            self._pages=[];self._error=localize(_msg('presetPreview.failed'))
        self.changed.emit()

    def _report(self,options):
        from voxplane.core.measurement_report import pdf_bytes
        rows=[dict(patient='DEMO-001' if not options['anonymous'] else '—',series='CT DEMO',modality='CT',view='2D',slice=26,id='M001',kind='ROI',mean=3.2,std=5.1,minimum=-12.4,maximum=18.7,area_mm2=490.87,width_mm=25.,height_mm=25.,pixel_count=1970,unit='HU',origin=(0.,0.,25.),orientation=(1.,0.,0.,0.,1.,0.)),
              dict(patient='DEMO-001' if not options['anonymous'] else '—',series='CT DEMO',modality='CT',view='2D',slice=26,id='M002',kind='Length',length_mm=38.4,unit='mm')]
        data=pdf_bytes(rows,options=options,created='2026-01-01 12:00',images=[('M001 · CT DEMO',example_image(layers=dict(parameters=False,directions=False,scale=False))),('M002 · CT DEMO',example_image(layers=dict(parameters=False,directions=False,scale=False),measurement_kind='length'))])
        source=QBuffer();source.setData(data);source.open(QIODevice.ReadOnly)
        document=QPdfDocument(self)
        try:
            document.load(source)
            pages=[]
            for i in range(document.pageCount()):
                points=document.pagePointSize(i)
                image=document.render(i,QSize(round(points.width()*3),round(points.height()*3)))
                if image.isNull(): raise ValueError('Empty PDF preview')
                white=QImage(image.size(),QImage.Format_RGB32);white.fill(QColor('white'))
                painter=QPainter(white);painter.drawImage(0,0,image);painter.end()
                pages.append(image_url(white))
            if not pages: raise ValueError('Empty PDF')
            self._pages=pages
            self._caption='A4 · '+localize(_msg('report.'+options['orientation']))
        finally:
            document.close();document.deleteLater();source.close()
