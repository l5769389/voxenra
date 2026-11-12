"""VTK objects live exclusively on the GUI thread of the native 3D widget."""
from voxplane.i18n import message as _msg
from dataclasses import replace
import logging
import math
import numpy as np
from vtkmodules.util.misc import calldata_type
from vtkmodules.util.numpy_support import numpy_to_vtk
from vtkmodules.vtkCommonCore import vtkUnsignedCharArray, vtkPoints, vtkOutputWindow, VTK_STRING
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonDataModel import vtkImageData, vtkPolyData, vtkCellArray
from vtkmodules.vtkFiltersSources import vtkCubeSource
from vtkmodules.vtkRenderingCore import (
    vtkRenderer, vtkVolume, vtkVolumeProperty, vtkColorTransferFunction,
    vtkActor, vtkPolyDataMapper, vtkPropAssembly,
    vtkActor2D, vtkPolyDataMapper2D, vtkCoordinate,
)
from vtkmodules.vtkCommonDataModel import vtkPiecewiseFunction
from vtkmodules.vtkRenderingVolumeOpenGL2 import vtkOpenGLGPUVolumeRayCastMapper
from vtkmodules.vtkRenderingAnnotation import vtkAnnotatedCubeActor
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
# Object-factory registration and font rendering; also visible to PyInstaller.
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
import vtkmodules.vtkRenderingFreeType  # noqa: F401
import vtkmodules.vtkInteractionStyle  # noqa: F401

from voxplane.core.volume_view import camera_parameters
from voxplane.core.volume_render_data import prepare_volume_data, volume_data_key
from voxplane.model.volume_models import VOLUME_DIRECTIONS, VolumeBlendMode, VolumeDisplayState
from voxplane.volume_presets import VOLUME_PRESET_BY_ID

logger = logging.getLogger(__name__)


def create_orientation_marker():
    """Color cube cells, not just vtkAnnotatedCubeActor's face text properties."""
    source = vtkCubeSource()
    source.Update()
    polydata = source.GetOutput()
    colors = vtkUnsignedCharArray()
    colors.SetNumberOfComponents(3)
    colors.SetName("FaceColors")
    for index in range(polydata.GetNumberOfCells()):
        points = polydata.GetCell(index).GetPoints()
        normal = np.mean([points.GetPoint(i) for i in range(points.GetNumberOfPoints())], axis=0)
        direction = max(VOLUME_DIRECTIONS, key=lambda d: np.dot(d.normal, normal))
        colors.InsertNextTuple3(*(int(direction.color[i:i+2], 16) for i in (1, 3, 5)))
    polydata.GetCellData().SetScalars(colors)
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    mapper.SetScalarModeToUseCellData()
    mapper.SetColorModeToDirectScalars()
    surface = vtkActor()
    surface.SetMapper(mapper)
    surface.GetProperty().LightingOff()
    labels = vtkAnnotatedCubeActor()
    # The separate outline actor rasterizes edge-on side letters as white
    # strokes beyond the cube. Keep only the flat, filled face glyphs.
    labels.SetTextEdgesVisibility(False)
    labels.GetCubeProperty().SetOpacity(0)
    for axis, positive, negative in (("X", "L", "R"), ("Y", "P", "A"), ("Z", "S", "I")):
        for side, face in (("Plus", positive), ("Minus", negative)):
            getattr(labels, f"Set{axis}{side}FaceText")(face)
            prop = getattr(labels, f"Get{axis}{side}FaceProperty")()
            prop.SetColor(1, 1, 1)
            prop.LightingOff()
    labels.GetTextEdgesProperty().SetColor(1, 1, 1)
    labels.GetTextEdgesProperty().LightingOff()
    assembly = vtkPropAssembly()
    assembly.AddPart(surface)
    assembly.AddPart(labels)
    return assembly, labels, surface


def create_transfer_functions(preset, window, opacity_scale=1.0):
    if not np.isfinite(window.width) or not np.isfinite(window.center) or window.width <= 0:
        raise ValueError(_msg('text.0014'))
    low = float(window.center)-window.width/2
    colors = vtkColorTransferFunction()
    for position, red, green, blue in preset.colors:
        colors.AddRGBPoint(low+window.width*position, red, green, blue)
    opacity = vtkPiecewiseFunction()
    for position, alpha in preset.opacity:
        opacity.AddPoint(low+window.width*position, alpha*opacity_scale)
    return colors, opacity


def volume_to_vtk(volume, prepared=None):
    geometry = volume.geometry
    prepared = prepared if prepared is not None else prepare_volume_data(volume)
    pixels = prepared.pixels
    spacing = (geometry.column_spacing, geometry.row_spacing, geometry.slice_spacing)
    image = vtkImageData()
    image.SetDimensions(geometry.columns, geometry.rows, geometry.slice_count)
    image.SetSpacing(*spacing)
    image.SetOrigin(*geometry.origin_patient)
    directions = np.column_stack((geometry.column_index_direction_patient,
                                  geometry.row_index_direction_patient,
                                  geometry.slice_index_direction_patient))
    image.SetDirectionMatrix(directions.ravel().tolist())
    # C-order data already has x (column) varying fastest. No transpose/quantization.
    image.GetPointData().SetScalars(numpy_to_vtk(pixels.reshape(-1), deep=False))
    return image, pixels


class VolumeRenderBackend:
    # Quantitative, unshaded PET keeps its physical image-grid convention.
    use_index_grid = True

    def __init__(self, widget):
        self.widget = widget
        self.window = widget.GetRenderWindow()
        self.window.SetMultiSamples(0)
        self.renderer = vtkRenderer()
        self.renderer.SetBackground(2/255, 7/255, 14/255)
        self.window.AddRenderer(self.renderer)
        # A binary GPU mask excludes voxels in composite, MIP and additive
        # rendering without substituting an intensity that windowing can reveal.
        self.mapper = vtkOpenGLGPUVolumeRayCastMapper()
        self.mapper.SetBlendModeToComposite()
        # Keep the same ray step while dragging and after release. VTK's
        # interactive adjustment otherwise trades sampling quality for its
        # requested frame rate, which makes the volume visibly blur and then
        # snap back when interaction stops.
        self.mapper.SetAutoAdjustSampleDistances(False)
        self.mapper.SetLockSampleDistanceToInputSpacing(False)
        self.mapper.SetImageSampleDistance(1.0)
        self.mapper.SetMaskTypeToBinary()
        self.actor = vtkVolume()
        self.actor.SetMapper(self.mapper)
        self.properties = vtkVolumeProperty()
        self.properties.SetInterpolationTypeToLinear()
        self.properties.ShadeOn()
        self.properties.SetAmbient(0.3)
        self.properties.SetDiffuse(0.7)
        self.properties.SetSpecular(0.15)
        self.actor.SetProperty(self.properties)
        self.renderer.AddVolume(self.actor)
        self.selection_data = vtkPolyData()
        selection_mapper = vtkPolyDataMapper2D()
        selection_mapper.SetInputData(self.selection_data)
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToNormalizedViewport()
        selection_mapper.SetTransformCoordinate(coordinate)
        self.selection_actor = vtkActor2D()
        self.selection_actor.SetMapper(selection_mapper)
        self.selection_actor.GetProperty().SetColor(1, 0.8, 0.2)
        self.selection_actor.GetProperty().SetLineWidth(2)
        self.selection_actor.SetVisibility(False)
        self.renderer.AddViewProp(self.selection_actor)
        self.renderer.GetActiveCamera().ParallelProjectionOn()
        self.orientation_actor, self.cube, self.cube_surface = create_orientation_marker()
        self.marker = vtkOrientationMarkerWidget()
        self.marker.SetOrientationMarker(self.orientation_actor)
        self.marker.SetInteractor(self.window.GetInteractor())
        self.marker.SetCurrentRenderer(self.renderer)
        # Antialias the small orientation overlay without changing volume
        # sampling or enabling MSAA on the GPU volume render window.
        self.marker.GetRenderer().UseFXAAOn()
        self._initialized = False
        self.volume = None
        self._image = None
        self._pixels = None
        self._sample_distance = None
        self._applied_display = None
        self._mask_source = None
        self._mask_image = self._mask_pixels = None
        self._error = False
        self._error_details = []
        self._observers = [(obj, obj.AddObserver("ErrorEvent", self._on_error))
                           for obj in (self.window, self.mapper)]

    @calldata_type(VTK_STRING)
    def _on_error(self, obj, event, detail=None):
        self._error = True
        if detail:
            text = str(detail).strip()
            self._error_details.append(text)
            logger.error("VTK %s: %s", event, text)

    def _check_render_errors(self):
        if self._error:
            detail = self._error_details[-1][:1500] if self._error_details else ""
            raise RuntimeError(_msg('text.0019') + ("\n" + detail if detail else ""))

    def preparation_key(self, volume):
        return volume_data_key(volume)

    def preparation_request(self, volume):
        return prepare_volume_data, (volume,)

    def set_volume(self, volume, prepared=None):
        prepared = prepared if prepared is not None else prepare_volume_data(volume)
        image, pixels = volume_to_vtk(volume, prepared)
        # Use the same GPU geometry convention as Slicer: a unit IJK grid
        # transformed into patient LPS by the actor. Encoding anisotropic
        # spacing in vtkImageData instead produces different gradient lighting
        # in the GPU mapper (particularly visible on thick CT slices).
        if self.use_index_grid:
            matrix = vtkMatrix4x4()
            matrix.DeepCopy(volume.geometry.voxel_to_patient[:, [2, 1, 0, 3]].ravel())
            image.SetOrigin(0, 0, 0)
            image.SetSpacing(1, 1, 1)
            image.SetDirectionMatrix(1, 0, 0, 0, 1, 0, 0, 0, 1)
            self.actor.SetUserMatrix(matrix)
        self.mapper.SetInputData(image)
        geometry = volume.geometry
        minimum_spacing = min(geometry.column_spacing, geometry.row_spacing, geometry.slice_spacing)
        # CT uses quarter-voxel sampling. MR uses half-voxel sampling, validated
        # against Slicer's Normal output: quarter-voxel steps can trigger macOS GPU
        # hangs in composite MR, even for a 256 x 256 x 192 volume.
        # Keep this fixed during interaction as well as after release.
        divisor = 2 if volume.representative_instance_meta.mr_parameters is not None else 4
        self._sample_distance = minimum_spacing / divisor if self.use_index_grid else minimum_spacing
        self.mapper.SetSampleDistance(self._sample_distance)
        self._image, self._pixels, self.volume = image, pixels, volume
        self._applied_display = None
        self._source_validity_mask = prepared.validity
        self._source_validity_pixels = prepared.mask_pixels
        self._mask_source = object()  # Force first application, including None.
        self._mask_image = self._mask_pixels = None
        self.apply_mask(None)

    def apply_mask(self, mask):
        if mask is self._mask_source:
            return
        source_mask = mask
        validity = getattr(self, "_source_validity_mask", None)
        if validity is not None:
            mask = validity if mask is None else (np.asarray(mask, dtype=bool) & validity)
        if mask is None:
            self.mapper.SetMaskInput(None)
            self._mask_image = self._mask_pixels = None
        else:
            if mask.shape != self._pixels.shape:
                raise ValueError(_msg('text.0018'))
            pixels = (self._source_validity_pixels if mask is validity
                      else np.ascontiguousarray(mask, dtype=np.uint8) * 255)
            image = vtkImageData()
            image.CopyStructure(self._image)
            image.GetPointData().SetScalars(numpy_to_vtk(pixels.ravel(), deep=False))
            self.mapper.SetMaskInput(image)
            self._mask_image, self._mask_pixels = image, pixels
        self._mask_source = source_mask

    def set_selection(self, points, size):
        self.selection_actor.SetVisibility(bool(points) and size is not None)
        if not points or size is None:
            return
        vertices, lines = vtkPoints(), vtkCellArray()
        for x, y in points:
            vertices.InsertNextPoint(x/max(1, size[0]), 1-y/max(1, size[1]), 0)
        lines.InsertNextCell(len(points)+1)
        for index in range(len(points)):
            lines.InsertCellPoint(index)
        lines.InsertCellPoint(0)
        self.selection_data.SetPoints(vertices)
        self.selection_data.SetLines(lines)
        self.selection_data.Modified()

    def apply_display(self, state):
        if self.volume is None:
            return
        preset = VOLUME_PRESET_BY_ID[state.preset_id]
        if state.window is None:
            state = replace(state, window=preset.default_window or self.volume.default_window)
        if state == self._applied_display:
            return
        # Source MONOCHROME1 polarity also applies to MR volume presentation.
        negative = (preset.group == "MR" and self.volume.representative_instance_meta.photometric_interpretation == "MONOCHROME1")
        if negative:
            preset = replace(preset, colors=tuple((1-p, r,g,b) for p,r,g,b in reversed(preset.colors)),
                             opacity=tuple((1-p,a) for p,a in reversed(preset.opacity)))
        additive = preset.blend_mode == VolumeBlendMode.ADDITIVE
        opacity_scale = 1.0
        if additive:
            # VTK already corrects additive opacity for sample distance. Scale
            # by the opacity unit distance, not the ray step: applying the step
            # twice makes XRay darker when sampling becomes denser.
            g = self.volume.geometry
            unit = preset.opacity_unit_distance
            diagonal = np.linalg.norm(((g.columns-1)*g.column_spacing,
                                       (g.rows-1)*g.row_spacing,
                                       (g.slice_count-1)*g.slice_spacing))
            opacity_scale = min(1.0, 3*unit/max(unit, diagonal))
            self.mapper.SetBlendModeToAdditive()
        else:
            if preset.blend_mode == VolumeBlendMode.MIP:
                if negative: self.mapper.SetBlendModeToMinimumIntensity()
                else: self.mapper.SetBlendModeToMaximumIntensity()
            else:
                self.mapper.SetBlendModeToComposite()
        colors, opacity = create_transfer_functions(preset, state.window, opacity_scale)
        self.properties.SetColor(colors)
        self.properties.SetScalarOpacity(opacity)
        self.properties.SetScalarOpacityUnitDistance(preset.opacity_unit_distance)
        self.properties.SetShade(preset.shade)
        self.properties.SetAmbient(preset.ambient)
        self.properties.SetDiffuse(preset.diffuse)
        self.properties.SetSpecular(preset.specular)
        self.properties.SetSpecularPower(preset.specular_power)
        self._applied_display = state

    def apply_state(self, state):
        if self.volume is None:
            return
        width, height = max(1, self.widget.width()), max(1, self.widget.height())
        geometry = getattr(self, "camera_geometry", self.volume.geometry)
        p = camera_parameters(geometry, state, (width, height))
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(*p["position"])
        camera.SetFocalPoint(*p["focal"])
        camera.SetViewUp(*p["up"])
        camera.SetParallelScale(p["scale"])
        camera.SetClippingRange(*p["clipping"])
        # Size in logical pixels: shrink the orientation aid with a small MPR
        # cell, retain readable labels normally, and cap its share in tiny cells.
        short_side = min(width, height)
        edge = min(96, max(48, short_side * .18), short_side * .25)
        margin = min(12, max(2, short_side * .025), (short_side-edge)/2)
        self.marker.SetViewport((width-margin-edge)/width, (height-margin-edge)/height,
                                (width-margin)/width, (height-margin)/height)

    def render(self, state, interactive=False, display_state=None, mask=None):
        if self.volume is None:
            return
        self._error = False
        self._error_details.clear()
        # Shader/texture errors originate below the mapper and do not always
        # propagate to its ErrorEvent. Scope the global sink to this GUI draw.
        output = vtkOutputWindow.GetInstance()
        observer = output.AddObserver("ErrorEvent", self._on_error)
        try:
            self._render_frame(state, display_state, mask)
            self._check_render_errors()
        finally:
            output.RemoveObserver(observer)

    def _render_frame(self, state, display_state, mask):
        self.apply_display(display_state or VolumeDisplayState())
        self.apply_mask(mask)
        if not self._initialized:
            # VTK may fall back to a headless window when native OpenGL fails.
            # It cannot present into QVTK's native child; OSMesa can even claim
            # support with no runtime DLL and crash on the first GL call.
            if self.window.GetClassName() in {"vtkOSOpenGLRenderWindow", "vtkEGLRenderWindow"}:
                logger.error("Native 3D requires a window-backed OpenGL context; got %s",
                             self.window.GetClassName())
                raise RuntimeError(_msg('volume.openGLUnavailable'))
            if not self.window.SupportsOpenGL():
                logger.error("3D OpenGL unavailable: %s", self.window.GetOpenGLSupportMessage())
                raise RuntimeError(_msg('volume.openGLUnavailable'))
            self.widget.Initialize()
            self._check_render_errors()
            # Input is handled by the Python controller, not the default VTK style.
            self.window.GetInteractor().SetInteractorStyle(None)
            self.marker.SetEnabled(True)
            self.marker.InteractiveOff()
            self._initialized = True
            logger.info("3D graphics capabilities: %s", self.window.ReportCapabilities())
        self.apply_state(state)
        if hasattr(self, "mpr_reference"):
            self.mpr_reference.project_marker(self.widget.devicePixelRatioF())
        # DesiredUpdateRate also feeds VTK's interactive quality heuristics.
        # Keep it identical so an interactive render and its settled render
        # use the same quality path. The host already coalesces pointer events.
        self.window.SetDesiredUpdateRate(0.01)
        # Bound screen-space rays on HiDPI/large windows. Preserve full voxel
        # data, physical ray step, transfer functions and crop/validity masks.
        # Use the same setting during dragging and at rest to avoid popping.
        width, height = self.window.GetSize()
        self.mapper.SetImageSampleDistance(min(4.0, max(1.0, math.sqrt(width * height / 1_000_000))))
        self.window.Render()

    def dispose(self):
        if self._initialized:
            self.marker.SetEnabled(False)
        self.marker.SetInteractor(None)
        for obj, observer in self._observers:
            obj.RemoveObserver(observer)
        self._observers.clear()
        self.renderer.RemoveAllViewProps()
        self.mapper.RemoveAllInputs()
        self.mapper.SetMaskInput(None)
        self.window.RemoveRenderer(self.renderer)
        self.widget.Finalize()
        self.volume = self._image = self._pixels = self._sample_distance = None
        self._applied_display = None
        self._mask_source = self._mask_image = self._mask_pixels = None
        self._source_validity_mask = self._source_validity_pixels = None
