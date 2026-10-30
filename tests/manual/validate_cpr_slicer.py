"""Independent Slicer 5.12 CPR oracle. See docs/validation/cpr-slicer-20261030.md.

CPR_VALIDATION_ROOT=/absolute/output .venv/bin/python tests/manual/validate_cpr_slicer.py
CPR_VALIDATION_STAGE=slicer CPR_VALIDATION_ROOT=... Slicer --no-main-window \
  --ignore-slicerrc --python-script tests/manual/validate_cpr_slicer.py

Preparation uses Voxenra; the Slicer stage never imports Voxenra. GUI acceptance
is deliberately separate. Generated DICOMs/scenes/pixels stay in ignored build/.
"""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import traceback

import numpy as np

ROOT = Path(os.environ.get('CPR_VALIDATION_ROOT', 'build/cpr-slicer-validation')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f4').tobytes()).hexdigest()


def write_dicom(name, pixels, ijk_to_lps):
    """Synthetic/transcoded test sources, never original clinical DICOM identity."""
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
    folder = ROOT / name
    folder.mkdir(exist_ok=True)
    uid, study, frame = (generate_uid() for _ in range(3))
    spacing = np.linalg.norm(ijk_to_lps[:3, :3], axis=0)
    directions = ijk_to_lps[:3, :3] / spacing
    for k, image in enumerate(pixels):
        path = folder / f'{k:04}.dcm'
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, uid, frame
        ds.PatientName, ds.PatientID = 'CPR^VALIDATION', 'NONCLINICAL-CPR'
        ds.Modality, ds.SeriesDescription, ds.StudyDescription = 'CT', name, 'CPR independent verification'
        ds.StudyDate, ds.StudyTime = '20261030', '120000'
        ds.ImageType, ds.InstanceNumber = ['DERIVED', 'SECONDARY', 'AXIAL'], k + 1
        ds.Rows, ds.Columns = image.shape
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 1
        ds.PixelSpacing, ds.SliceThickness = [float(spacing[1]), float(spacing[0])], float(spacing[2])
        ds.ImageOrientationPatient = directions[:, :2].T.ravel().tolist()
        ds.ImagePositionPatient = (ijk_to_lps @ [0, 0, k, 1])[:3].tolist()
        ds.RescaleIntercept, ds.RescaleSlope, ds.RescaleType = 0, 1, 'HU'
        ds.WindowCenter, ds.WindowWidth, ds.BurnedInAnnotation = 300, 1800, 'NO'
        ds.PixelData = np.asarray(image, dtype='<i2').tobytes()
        ds.save_as(path, enforce_file_format=True)
    return folder


def download_public():
    import slicer, vtk, SampleData
    node = SampleData.downloadSample('CTACardio')
    source = Path(node.GetStorageNode().GetFileName())
    source_info = dict(sample='CTACardio', filename=source.name,
                       sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                       url='https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/3b0d4eb1a7d8ebb0c5a89cc0504640f76a030b4e869e33ff34c564c3d3b88ad2')
    assert source_info['sha256'] == source_info['url'].rsplit('/',1)[1]
    matrix = vtk.vtkMatrix4x4(); node.GetIJKToRASMatrix(matrix)
    affine = np.diag([-1,-1,1,1])@np.array([[matrix.GetElement(i,j) for j in range(4)] for i in range(4)])
    np.savez_compressed(ROOT/'public-cta.npz', pixels=slicer.util.arrayFromVolume(node), ijk_to_lps=affine)
    (ROOT/'public-cta-source.json').write_text(json.dumps(source_info,indent=2))
    slicer.app.exit(0)


def prepare():
    from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
    from qt_dicom_viewer.core.volume_manager import VolumeManager
    from qt_dicom_viewer.core.cpr_reslicer import CprReslicer
    from qt_dicom_viewer.core.cpr_session import unpack_path
    from qt_dicom_viewer.core.workspace_document import read_document
    from qt_dicom_viewer.core.workspace_state import loads
    from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
    from qt_dicom_viewer.model.cpr import CprPath, CprSettings

    repo = Path(__file__).resolve().parents[2]
    workspace_path = ROOT/'native-ui.voxworkspace'
    if workspace_path.exists():
        tab = read_document(workspace_path)['tabs'][0]
        session = tab['edits']['cpr']
        cross_view = next(value for key,value in tab['edits']['views'].items() if key.endswith('|cross'))
    else:
        fixture = loads((repo/'tests/fixtures/cpr_slicer_native.json').read_bytes())
        session, cross_view = fixture['session'],fixture['cross']
    paths = [unpack_path(record) for record in session['paths']]
    native = repo/'build/native-cpr/synthetic-ct'
    if not native.exists():
        yy,xx = np.mgrid[:160,:160]
        body = ((xx-80)/65)**2+((yy-80)/58)**2 < 1
        slices = []
        for z in range(96):
            pixels = np.where(body,40+15*np.sin(xx/12),-900)
            for center in (80+23*np.sin((z-45)/24),45+10*np.cos(z/22)):
                radius = np.hypot(xx-center,yy-80)
                pixels += np.where(body,1350*np.exp(-.5*(radius/3)**2),0)
            slices.append(pixels.astype('int16'))
        native = write_dicom('native-phantom',np.stack(slices),np.diag([.8,.8,1,1]))
    # Deliberately oblique, anisotropic source and a non-planar path. Values encode
    # IJK position, so axis/handedness/spacing errors cannot hide in symmetry.
    ax, az = np.deg2rad([23, 37])
    rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    affine = np.eye(4)
    affine[:3, :3] = rz @ rx @ np.diag([.6, 1.1, 1.7])
    affine[:3, 3] = [-71, -43, 19]
    k, j, i = np.indices((48, 64, 80))
    oblique = write_dicom('oblique-phantom', (-800 + i * 3 + j * 5 + k * 9).astype('int16'), affine)
    ijks = np.array([[12, 20, 8], [28, 26, 17], [42, 42, 23], [63, 36, 38]])
    p = ijks @ affine[:3, :3].T + affine[:3, 3]
    cases = [('native', native, paths),
             ('oblique', oblique, [(CprPath('oblique', 'Oblique nonplanar', tuple(map(tuple, p))),
                                    CprSettings(width_mm=24, step_mm=.75))])]
    public = ROOT / 'public-cta.npz'
    if public.exists():
        with np.load(public) as data:
            # Central heart crop. Geometric verification path, NOT a claimed
            # coronary centerline or an anatomical/clinical validation.
            pixels = data['pixels'][100:220, 150:370, 150:370].copy()
            a = data['ijk_to_lps'].copy()
            a[:3, 3] = (a @ [150, 150, 100, 1])[:3]
        folder = write_dicom('public-cta-crop', pixels, a)
        theta = np.linspace(0, np.pi * 1.5, 31)
        ijk = np.c_[110 + 26 * np.cos(theta), 110 + 26 * np.sin(theta), np.linspace(20, 95, len(theta))]
        pts = ijk @ a[:3, :3].T + a[:3, 3]
        cases.append(('public-cta', folder, [(CprPath('public-cta', 'CTA geometric test path', tuple(map(tuple, pts))),
                                             CprSettings(width_mm=30, step_mm=.6))]))
    manifest = {'tolerances': {'affine_mm': 1e-5, 'length_mm': 1e-5, 'position_mm': 1e-5,
                               'pixel_max_hu': .1, 'pixel_mean_hu': .01, 'frame_dot': 1e-6},
                'cases': [], 'historical': []}
    reslicer = CprReslicer()
    for name, folder, path_records in cases:
        files = sorted(folder.glob('*.dcm'))
        scanned = list(DicomFolderScanner().scan_files(files, folder=folder, can_publish=lambda: False))[-1]
        assert len(scanned.series) == 1
        volume = VolumeManager().get_or_build(scanned.series[0])
        case = {'name': name, 'files': list(map(str, files)), 'shape': list(volume.modality_pixels.shape),
                'source_digest': digest(volume.modality_pixels),
                'kji_to_lps': volume.geometry.voxel_to_patient.tolist(), 'runs': []}
        for path_index, (path, original) in enumerate(path_records):
            settings_list = [('saved', original)]
            settings_list += [(mode, replace(original, projection=mode, thickness_mm=9,
                                             angle_radians=np.deg2rad(37), step_mm=.8))
                              for mode in ('thin', 'mip', 'mean')]
            if name == 'oblique':
                # Explicit source-boundary coverage; invalid pixels must stay NaN.
                settings_list.append(('wide-boundary', replace(original, width_mm=120,
                                      projection='mean', thickness_mm=12, step_mm=1.5)))
            for mode, settings in settings_list:
                key = f'{name}-{path_index}-{mode}'
                result = reslicer.reslice(volume, path, settings)
                line = result.centerline
                offsets = np.linspace(-settings.width_mm / 2, settings.width_mm / 2, result.modality_pixels.shape[0])
                arrays = dict(pixels=result.modality_pixels, points=line.points_patient,
                              distances=line.distances_mm, tangents=line.tangents_patient,
                              laterals=line.laterals_patient, binormals=line.binormals_patient, offsets=offsets)
                indices = sorted(set([0, len(line.distances_mm)//2, len(line.distances_mm)-1]))
                for n, index in enumerate(indices):
                    section = reslicer.cross_section(volume, line, index, width_mm=20, step_mm=settings.step_mm)
                    arrays[f'cross{n}'] = section.modality_pixels
                np.savez_compressed(ROOT / f'{key}.npz', **arrays)
                case['runs'].append({'key': key, 'path': asdict(path), 'settings': asdict(settings),
                                     'sha256':hashlib.sha256((ROOT/f'{key}.npz').read_bytes()).hexdigest(),
                                     'cross_indices': indices, 'cross_width_mm': 20})
        if name == 'native':
            view = cross_view
            for mid, measurement in view['measurements'].items():
                source = view['sources'][mid]
                params = source['parameters']
                frame, grid = params['mpr_frame'], params['mpr_grid']
                origin = (np.asarray(frame.center_patient)
                          - np.asarray(frame.u_direction_patient) * (grid.columns-1)*grid.column_spacing/2
                          - np.asarray(frame.v_direction_patient) * (grid.rows-1)*grid.row_spacing/2)
                coordinates = [(point.column,point.row) for point in measurement.points]
                kind = 'length' if hasattr(measurement,'length_mm') else 'area'
                if kind == 'area':
                    assert measurement.kind.value == 'rect'
                    (x0,y0),(x1,y1) = coordinates
                    coordinates = [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
                points = [origin + np.asarray(frame.u_direction_patient)*x*grid.column_spacing
                          + np.asarray(frame.v_direction_patient)*y*grid.row_spacing for x,y in coordinates]
                restored = MprReslicer().reslice(volume, params['plane'], frame=frame, grid_spec=grid)
                np.save(ROOT/'historical-cross.npy', restored.modality_pixels)
                manifest['historical'].append(dict(points_lps=np.asarray(points).tolist(),
                    kind=kind, value=measurement.length_mm if kind == 'length' else measurement.metrics.area_mm2,
                    path_revision=source['cpr']['pathRevision'],
                    current_revision=path_records[0][0].revision, source=source['cpr'],
                    origin=origin.tolist(), u=list(frame.u_direction_patient), v=list(frame.v_direction_patient),
                    spacing=[grid.column_spacing, grid.row_spacing], shape=[grid.rows, grid.columns]))
                if kind == 'area':
                    manifest['historical'][-1].update(statistics=asdict(measurement.metrics),
                        rectangle=[[point.column,point.row] for point in measurement.points])
        manifest['cases'].append(case)
    (ROOT/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'cases': len(manifest['cases']), 'runs': sum(len(c['runs']) for c in manifest['cases'])}))


def slicer_oracle():
    import slicer
    import vtk
    from DICOMScalarVolumePlugin import DICOMScalarVolumePluginClass
    from vtk.util.numpy_support import numpy_to_vtk

    (ROOT/'slicer-report.json').unlink(missing_ok=True)
    (ROOT/'slicer-error.txt').unlink(missing_ok=True)
    manifest = json.loads((ROOT/'manifest.json').read_text())
    report = dict(slicer=slicer.app.applicationVersion, revision=slicer.app.repositoryRevision,
                  vtk=vtk.vtkVersion.GetVTKVersion(), tolerances=manifest['tolerances'], cases=[], historical=[],
                  manifest_sha256=hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest())
    ras_sign = np.array([-1., -1., 1.])
    logic = slicer.modules.generalizedreformat.logic()
    # Slicer 5.12's CLI resampler is registered without application logic in
    # --no-main-window mode. Initialize this service explicitly (no GUI calls).
    logic.GetVolumeResampler('ResampleScalarVectorDWIVolume').SetMRMLApplicationLogic(slicer.app.applicationLogic())

    def compare(actual, expected):
        mask = np.isfinite(actual) & np.isfinite(expected)
        difference = np.abs(actual[mask].astype(float) - expected[mask])
        return dict(max_hu=float(difference.max(initial=0)), mean_hu=float(difference.mean()) if len(difference) else None,
                    valid_pixels=int(mask.sum()), invalid_pixels=int((~np.isfinite(actual)).sum()),
                    mask_mismatch=int(np.count_nonzero(np.isfinite(actual) != np.isfinite(expected))))

    for case in manifest['cases']:
        node = DICOMScalarVolumePluginClass().loadFilesWithSeriesReader('GDCM', case['files'], case['name'])
        assert node, case['name']
        matrix = vtk.vtkMatrix4x4(); node.GetIJKToRASMatrix(matrix)
        ijk_ras = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
        ijk_lps = np.diag([-1, -1, 1, 1]) @ ijk_ras
        ras_ijk = np.linalg.inv(ijk_ras)
        pixels = slicer.util.arrayFromVolume(node)
        cr = dict(name=case['name'], source_shape=list(pixels.shape), source_digest_match=digest(pixels)==case['source_digest'],
                  affine_max_mm=float(np.max(np.abs(ijk_lps[:, [2,1,0,3]]-np.array(case['kji_to_lps'])))), runs=[])
        # Independent VTK interpolation, float input avoids integer truncation.
        image = vtk.vtkImageData(); image.DeepCopy(node.GetImageData())
        image.SetOrigin(0, 0, 0); image.SetSpacing(1, 1, 1)
        image.SetDirectionMatrix(1,0,0,0,1,0,0,0,1)
        image.GetPointData().SetScalars(numpy_to_vtk(pixels.astype(np.float32).ravel(), deep=True))
        interpolator = vtk.vtkImageInterpolator()
        interpolator.SetInterpolationModeToLinear(); interpolator.Initialize(image)
        upper = np.array(image.GetDimensions())-1

        def sample(lps):
            shape = lps.shape[:-1]
            coords = (lps.reshape(-1,3)*ras_sign)@ras_ijk[:3,:3].T+ras_ijk[:3,3]
            valid = np.all((coords >= -1e-6) & (coords <= upper+1e-6), axis=1)
            coords = np.clip(coords, 0, upper)
            out = np.full(len(coords), np.nan, dtype=np.float32)
            value = [0.]
            for index in np.flatnonzero(valid):
                interpolator.InterpolateIJK(coords[index], value)
                out[index] = value[0]
            return out.reshape(shape)

        for run in case['runs']:
            print('Validating '+run['key'], flush=True)
            assert hashlib.sha256((ROOT/(run['key']+'.npz')).read_bytes()).hexdigest()==run['sha256']
            data = np.load(ROOT/(run['key']+'.npz'))
            curve = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', run['key'])
            curve.SetCurveTypeToLinear(); curve.SetNumberOfPointsPerInterpolatingSegment(1)
            for point in run['path']['control_points']:
                curve.AddControlPoint(vtk.vtkVector3d(*(np.array(point)*ras_sign)))
            positions, tangents = [], []
            length = curve.GetCurveLengthWorld()
            for distance in data['distances']:
                position = [0.,0.,0.]
                endpoint = abs(float(distance)-length) < manifest['tolerances']['length_mm']
                if endpoint:
                    # Markups can return False at exactly length after roundoff
                    # in accumulated segment sums. The endpoint is unambiguous.
                    curve_points = curve.GetCurvePointsWorld()
                    position[:] = curve_points.GetPoint(curve_points.GetNumberOfPoints()-1)
                else:
                    assert curve.GetPositionAlongCurveWorld(position, 0, float(distance)), (run['key'], distance, length)
                positions.append(np.array(position)*ras_sign)
                # Forward derivative matches the declared outgoing tangent at a
                # polyline vertex; at the endpoint use the backward derivative.
                delta = 1e-5 if distance+1e-5 < length else -1e-5
                other = [0.,0.,0.]
                assert curve.GetPositionAlongCurveWorld(other, 0, (length if endpoint else float(distance))+delta)
                tangent = (np.array(other)-position)*ras_sign/delta
                tangents.append(tangent/np.linalg.norm(tangent))
            base = data['points'][None,:,:]+data['offsets'][:,None,None]*data['laterals'][None,:,:]
            settings = run['settings']
            # Independently construct the declared segment-frame transport with
            # VTK rotation matrices, rather than Voxenra's Rodrigues formula.
            # Slicer's default Markups frames average tangents at vertices and
            # therefore do not implement the same polyline convention.
            controls = np.array(run['path']['control_points'])*ras_sign
            segments = np.diff(controls,axis=0)
            segment_lengths = np.linalg.norm(segments,axis=1)
            directions = segments/segment_lengths[:,None]
            knots_exact = np.r_[0.,np.cumsum(segment_lengths)]
            up = np.array(settings['up_patient'])*ras_sign
            lateral = up-up.dot(directions[0])*directions[0]
            if np.linalg.norm(lateral)<1e-8:
                # Fallback basis is defined in LPS, including its sign in RAS.
                up = np.eye(3)[np.argmin(np.abs(directions[0]))]*ras_sign
                lateral = up-up.dot(directions[0])*directions[0]
            lateral /= np.linalg.norm(lateral)
            expected_laterals = []
            for n,tangent in enumerate(directions):
                if n:
                    axis = np.cross(directions[n-1],tangent)
                    sine = np.linalg.norm(axis)
                    if sine>1e-12:
                        rotation = vtk.vtkTransform()
                        rotation.RotateWXYZ(np.degrees(np.arctan2(sine,directions[n-1].dot(tangent))),axis/sine)
                        lateral = np.array(rotation.TransformVector(lateral))
                    lateral -= lateral.dot(tangent)*tangent
                    lateral /= np.linalg.norm(lateral)
                rotation = vtk.vtkTransform()
                rotation.RotateWXYZ(np.degrees(settings['angle_radians']),tangent)
                expected_laterals.append(np.array(rotation.TransformVector(lateral))*ras_sign)
            expected_frames = []
            for distance in data['distances']:
                segment = next((n for n,end in enumerate(knots_exact[1:]) if distance<end),len(directions)-1)
                expected_frames.append(expected_laterals[segment])
            transport_error = float(np.linalg.norm(np.array(expected_frames)-data['laterals'],axis=1).max())
            slab = np.array([0.])
            if settings['projection'] != 'thin' and settings['thickness_mm'] > 0:
                spacing = min(settings['step_mm'], float(np.min(np.linalg.svd(ijk_lps[:3,:3], compute_uv=False))))
                count = 2*int(np.ceil(settings['thickness_mm']/(2*spacing)))+1
                slab = np.linspace(-settings['thickness_mm']/2, settings['thickness_mm']/2, count)
            samples = np.stack([sample(base+offset*data['binormals'][None,:,:]) for offset in slab])
            valid = np.isfinite(samples)
            counts = valid.sum(axis=0)
            if settings['projection'] == 'mip':
                oracle = np.where(valid, samples, -np.inf).max(axis=0)
            else:
                oracle = np.where(valid, samples, 0).sum(axis=0, dtype=np.float64)/np.maximum(counts,1)
            oracle[counts == 0] = np.nan
            cross = []
            for n, index in enumerate(run['cross_indices']):
                offsets = np.linspace(-run['cross_width_mm']/2, run['cross_width_mm']/2, data[f'cross{n}'].shape[0])
                grid = (data['points'][index]+offsets[:,None,None]*data['binormals'][index]
                        +offsets[None,:,None]*data['laterals'][index])
                cross.append(compare(data[f'cross{n}'], sample(grid)))
            basis = np.stack([data['laterals'],data['binormals'],data['tangents']],axis=-1)
            # A polyline has no unique derivative at a vertex. Slicer's float32
            # curve tessellation can put a sample a few microns on the other
            # side; compare tangents only where the derivative is unambiguous.
            curve_points = curve.GetCurvePointsWorld()
            knots = np.r_[0., np.cumsum([np.linalg.norm(np.array(curve_points.GetPoint(i))-curve_points.GetPoint(i-1))
                                        for i in range(1,curve_points.GetNumberOfPoints())])]
            near_vertex = np.min(np.abs(data['distances'][:,None]-knots[None,1:-1]),axis=1) < 1e-4
            tangent_errors = np.linalg.norm(np.array(tangents)-data['tangents'],axis=1)
            rr = dict(key=run['key'], length_mm=length, length_error_mm=abs(length-float(data['distances'][-1])),
                      position_max_mm=float(np.max(np.linalg.norm(np.array(positions)-data['points'],axis=1))),
                      tangent_max_error=float(tangent_errors[~near_vertex].max(initial=0)),
                      vertex_samples=int(near_vertex.sum()), vertex_tangent_max_error=float(tangent_errors[near_vertex].max(initial=0)),
                      vtk_transport_roll_max_error=transport_error,
                      frame_orthonormal_error=float(np.max(np.abs(np.swapaxes(basis,-1,-2)@basis-np.eye(3)))),
                      frame_min_determinant=float(np.linalg.det(basis).min()), pixels=compare(data['pixels'], oracle), cross=cross)
            # Exercise the actual Slicer CPR module independently. Its smoothed
            # tangent/grid alignment differs; volume equality is NOT asserted.
            if run['key'].endswith('-saved'):
                transform = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTransformNode', run['key']+' straightening')
                output = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', run['key']+' Slicer CPR')
                ok = logic.ComputeStraighteningTransform(transform, curve, [settings['width_mm']]*2, settings['step_mm'])
                assert ok and logic.StraightenVolume(output,node,[settings['step_mm']]*3,transform)
                rr['builtin_cpr'] = dict(shape=list(slicer.util.arrayFromVolume(output).shape),
                                         spacing=list(output.GetSpacing()))
                mean = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode', run['key']+' Slicer mean')
                assert logic.ProjectVolume(mean,output,1)
                if case['name'] == 'native':
                    slicer.util.saveNode(output,str(ROOT/(run['key']+'-slicer-cpr.nrrd')))
            else:
                slicer.mrmlScene.RemoveNode(curve)
            cr['runs'].append(rr)
        if case['name'] == 'native':
            for record in manifest['historical']:
                kind = record['kind']
                line = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsLineNode' if kind == 'length' else 'vtkMRMLMarkupsClosedCurveNode',
                                                       'Historical cross-section '+kind)
                if kind == 'area':
                    line.SetCurveTypeToLinear();line.SetNumberOfPointsPerInterpolatingSegment(1)
                    line.GetMeasurement('area').SetEnabled(True)
                for point in record['points_lps']:
                    line.AddControlPoint(vtk.vtkVector3d(*(np.array(point)*ras_sign)))
                measurement = line.GetMeasurement(kind)
                units = measurement.GetUnits()
                factor = {'mm':1.,'mm2':1.,'mm²':1.,'cm2':100.,'cm²':100.}[units]
                # Units describe DisplayValue; Value is in the scene's base
                # units. Using Value with display units would scale area twice.
                actual = measurement.GetDisplayValue()*factor
                row,col = np.indices(record['shape'])
                grid = (np.array(record['origin'])+row[...,None]*record['spacing'][1]*np.array(record['v'])
                        +col[...,None]*record['spacing'][0]*np.array(record['u']))
                report['historical'].append(dict(kind=kind, saved=record['value'],slicer=actual,error=abs(actual-record['value']),
                    units='mm' if kind == 'length' else 'mm²', slicer_original_units=units,
                    path_revision=record['path_revision'],current_revision=record['current_revision'],
                    pixels=compare(np.load(ROOT/'historical-cross.npy'),sample(grid))))
                if kind == 'area':
                    (x0,y0),(x1,y1) = record['rectangle']
                    mask = (col >= min(x0,x1)) & (col <= max(x0,x1)) & (row >= min(y0,y1)) & (row <= max(y0,y1))
                    values = sample(grid)[mask].astype(np.float64)
                    values = values[np.isfinite(values)]
                    statistics = dict(pixel_count=len(values),mean=float(values.mean()),std=float(values.std()),
                                      minimum=float(values.min()),maximum=float(values.max()))
                    report['historical'][-1]['roi_statistics'] = statistics
                    report['historical'][-1]['roi_statistic_errors'] = {key:abs(value-record['statistics'][key]) for key,value in statistics.items()}
        report['cases'].append(cr)
    slicer.util.saveScene(str(ROOT/'cpr-reference.mrb'))
    (ROOT/'slicer-report.json').write_text(json.dumps(report,indent=2))
    check_report()
    slicer.app.exit(0)


def check_report():
    report = json.loads((ROOT/'slicer-report.json').read_text())
    manifest = json.loads((ROOT/'manifest.json').read_text())
    tolerance = report['tolerances']
    failures = []
    def check(condition, name):
        if not condition:
            failures.append(name)
    check(report['manifest_sha256']==hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest(),'matching input manifest')
    check(len(report['cases']) == len(manifest['cases']), 'all cases completed')
    for case, expected in zip(report['cases'],manifest['cases']):
        check(case['source_digest_match'],case['name']+' source pixels')
        check(case['affine_max_mm'] <= tolerance['affine_mm'],case['name']+' affine')
        check(len(case['runs']) == len(expected['runs']),case['name']+' all runs completed')
        for run in case['runs']:
            for name,limit in [('length_error_mm',tolerance['length_mm']),('position_max_mm',tolerance['position_mm']),
                               ('tangent_max_error',tolerance['frame_dot']),('frame_orthonormal_error',tolerance['frame_dot']),
                               ('vtk_transport_roll_max_error',tolerance['frame_dot'])]:
                check(run[name] <= limit,run['key']+' '+name)
            check(abs(run['frame_min_determinant']-1)<tolerance['frame_dot'],run['key']+' handedness')
            for image in [run['pixels'],*run['cross']]:
                check(image['valid_pixels'] > 0 and image['mask_mismatch']==0 and image['max_hu'] <= tolerance['pixel_max_hu']
                      and image['mean_hu'] <= tolerance['pixel_mean_hu'],run['key']+' image values/mask')
    check(len(report['historical'])==len(manifest['historical']), 'historical measurements completed')
    for record in report['historical']:
        check(record['error'] < (1e-5 if record['kind']=='length' else 1e-3), 'historical '+record['kind'])
        check(record['pixels']['mask_mismatch']==0 and record['pixels']['max_hu'] <= tolerance['pixel_max_hu'], 'historical image')
        if record['kind'] == 'area':
            check(record['roi_statistic_errors']['pixel_count']==0 and max(record['roi_statistic_errors'].values())<.1,'ROI statistics')
    report['checks_passed'] = not failures
    report['failures'] = failures
    (ROOT/'slicer-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=not failures,failures=failures)))
    assert not failures, failures


if __name__ == '__main__':
    if os.environ.get('CPR_VALIDATION_STAGE') in ('slicer', 'public'):
        try:
            if os.environ['CPR_VALIDATION_STAGE'] == 'public':
                download_public()
            else:
                slicer_oracle()
        except Exception:
            (ROOT/'slicer-error.txt').write_text(traceback.format_exc())
            import slicer
            slicer.app.exit(1)
    elif os.environ.get('CPR_VALIDATION_STAGE') == 'check':
        check_report()
    else:
        prepare()
