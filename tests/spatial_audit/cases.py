"""Small DICOM phantoms whose truth is defined before serialization.

Arrays use (slice,row,column); affines map that ordering to patient LPS.
Neither generation nor reference sampling imports Voxenra code.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, MRImageStorage, EnhancedCTImageStorage,
                        PositronEmissionTomographyImageStorage, ExplicitVRLittleEndian, RLELossless)


@dataclass(frozen=True)
class Case:
    name: str
    orientation: str = 'axial'
    spacing: tuple = (2.4, .7, .5)
    modality: str = 'CT'
    defect: str = ''
    slope: float = .5
    intercept: float = -1024
    signed: bool = True
    mono1: bool = False
    padding: bool = False
    rle: bool = False
    enhanced: bool = False
    per_frame_scale: bool = False
    phases: int = 1
    pet_units: str = 'BQML'
    pet_missing: str = ''
    midnight: bool = False


CASES = [Case('ct-'+o, o) for o in ('axial','coronal','sagittal','flipped','oblique')]
CASES += [Case('ct-isotropic', spacing=(1.,1.,1.)),
          Case('ct-thick-gap', spacing=(5.,.6,.9)), Case('ct-unsigned', signed=False),
          Case('ct-rle', rle=True), Case('ct-padding', padding=True),
          Case('ct-per-slice-scale', per_frame_scale=True),
          Case('ct-classic-phases', phases=2, per_frame_scale=True),
          Case('mr-mono1', modality='MR', mono1=True, slope=.25, intercept=-3),
          Case('mr-oblique', 'oblique', modality='MR', slope=1, intercept=0),
          Case('enhanced-ct', enhanced=True),
          Case('enhanced-ct-phases', enhanced=True, phases=2, per_frame_scale=True),
          Case('enhanced-ct-rle', enhanced=True, rle=True, per_frame_scale=True)]
CASES += [Case('invalid-'+d, defect=d) for d in
          ('duplicate-position','nonuniform','shear','orientation','missing-spacing',
           'zero-spacing','missing-position','frame-of-reference','uniform-shear','nan-spacing','nonorthogonal')]
CASES += [Case('duplicate-file', defect='duplicate-file')]
CASES += [Case('pet-'+n, modality='PT', slope=2, intercept=0, signed=False, **kw)
          for n,kw in [('bqml',{}), ('midnight',{'midnight':True}),
                       ('gml',{'pet_units':'GML'}), ('no-weight',{'pet_missing':'PatientWeight'}),
                       ('no-dose',{'pet_missing':'RadionuclideTotalDose'})]]


def uid(text):
    return '2.25.'+str(int.from_bytes(hashlib.sha256(text.encode()).digest()[:16], 'big'))


def directions(name):
    if name == 'axial': return np.eye(3)
    if name == 'coronal': return np.array([[1,0,0],[0,0,-1],[0,1,0]], float)
    if name == 'sagittal': return np.array([[0,0,1],[1,0,0],[0,1,0]], float)
    if name == 'flipped': return np.diag([-1,1,-1])
    a,b,c=np.deg2rad([23,-17,31])
    rx=np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
    ry=np.array([[np.cos(b),0,np.sin(b)],[0,1,0],[-np.sin(b),0,np.cos(b)]])
    rz=np.array([[np.cos(c),-np.sin(c),0],[np.sin(c),np.cos(c),0],[0,0,1]])
    return rz@ry@rx


def item(**kwargs):
    ds=Dataset()
    for key,value in kwargs.items(): setattr(ds,key,value)
    return ds


def generate(root, case):
    root=Path(root); root.mkdir(parents=True, exist_ok=True)
    shape=(9,17,23); zz,yy,xx=np.indices(shape)
    # Deliberately asymmetric, exactly trilinear away from the marker/padding.
    raw=(41*zz+7*yy+3*xx-(120 if case.signed else 0)).astype('<i2' if case.signed else '<u2')
    raw[1,3,5]=1701
    if case.padding: raw[:,0,:]=-2048
    rotation=directions(case.orientation)
    origin=np.array([-31.25,17.75,-12.5])
    affine=np.eye(4); affine[:3,:3]=rotation[:,::-1]*case.spacing; affine[:3,3]=origin
    storage=(EnhancedCTImageStorage if case.enhanced else
             {'CT':CTImageStorage,'MR':MRImageStorage,'PT':PositronEmissionTomographyImageStorage}[case.modality])
    def base(identifier):
        meta=FileMetaDataset(); meta.TransferSyntaxUID=ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID=storage; meta.MediaStorageSOPInstanceUID=uid(identifier)
        ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
        for key,value in dict(SOPClassUID=storage,SOPInstanceUID=meta.MediaStorageSOPInstanceUID,
            StudyInstanceUID=uid(case.name+'study'),SeriesInstanceUID=uid(case.name+'series'),
            FrameOfReferenceUID=uid(case.name+'frame'),PatientName='Spatial^Phantom',PatientID='AUDIT',
            StudyDate='20260101',StudyTime='130000',SeriesNumber=1,StudyID='1',
            SeriesDescription=case.name,Modality=case.modality,ImageType=['ORIGINAL','PRIMARY','VOLUME'],
            PatientPosition='HFDR' if case.orientation=='sagittal' else 'HFS',
            Rows=shape[1],Columns=shape[2],SamplesPerPixel=1,
            PhotometricInterpretation='MONOCHROME1' if case.mono1 else 'MONOCHROME2',
            BitsAllocated=16,BitsStored=16,HighBit=15,PixelRepresentation=int(case.signed),
            PixelSpacing=list(case.spacing[1:]),SliceThickness=1.,SpacingBetweenSlices=case.spacing[0],
            ImageOrientationPatient=rotation[:,:2].T.ravel().tolist(),
            WindowCenter=0,WindowWidth=1000).items(): setattr(ds,key,value)
        if case.padding: ds.PixelPaddingValue=-2048
        if case.modality=='MR':
            ds.ScanningSequence='GR'; ds.SequenceVariant='SK'; ds.MRAcquisitionType='3D'
            ds.RepetitionTime=10; ds.EchoTime=2; ds.FlipAngle=15
        if case.modality=='PT':
            ds.SeriesType=['STATIC','IMAGE']; ds.Units=case.pet_units; ds.SUVType='BW'
            ds.PatientWeight=70; ds.CorrectedImage=['ATTN','DECY']; ds.DecayCorrection='START'
            ds.AcquisitionDateTime='20260102001000' if case.midnight else '20260101130000'
            ds.SeriesDate=ds.AcquisitionDateTime[:8]; ds.SeriesTime=ds.AcquisitionDateTime[8:]
            ds.RadiopharmaceuticalInformationSequence=[item(Radiopharmaceutical='F-18 FDG',
                RadiopharmaceuticalStartDateTime='20260101235000' if case.midnight else '20260101120000',
                RadionuclideTotalDose=350000000.,RadionuclideHalfLife=6586.2)]
            if case.pet_missing=='PatientWeight': del ds.PatientWeight
            if case.pet_missing=='RadionuclideTotalDose': del ds.RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose
        return ds
    truth={}; frames=[]; data=[]; paths=[]; sources=[]
    # Nonspatial dimensions interleaved, spatial file order deliberately reversed.
    for z in reversed(range(shape[0])):
        for phase in range(case.phases):
            slope=case.slope+z/8 if case.per_frame_scale else case.slope
            intercept=case.intercept+phase*10
            stored=raw[z]+phase*100
            values=stored.astype(float)*slope+intercept
            if case.padding: values[raw[z]==-2048]=np.nan
            truth.setdefault(phase,[]).append((z,values))
            pos=origin+affine[:3,0]*z
            if case.defect=='uniform-shear': pos=pos+rotation[:,0]*.2*z
            if z==4:
                if case.defect=='duplicate-position': pos=origin+affine[:3,0]*3
                if case.defect=='nonuniform': pos=pos+affine[:3,0]*.3
                if case.defect=='shear': pos=pos+rotation[:,0]*.5
            index=len(frames)
            if case.enhanced:
                frames.append(item(FrameContentSequence=[item(StackID='1',InStackPositionNumber=z+1,
                    TemporalPositionIndex=phase+1,DimensionIndexValues=[z+1,phase+1])],
                    PlanePositionSequence=[item(ImagePositionPatient=pos.tolist())],
                    PixelValueTransformationSequence=[item(RescaleSlope=slope,RescaleIntercept=intercept,RescaleType='HU')]))
                data.append(stored)
                sources.append(dict(z=z,phase=phase,frame=index,path='enhanced.dcm'))
            else:
                ds=base(case.name+str(z)+('phase'+str(phase) if case.phases>1 else '')); ds.ImagePositionPatient=pos.tolist()
                if case.phases>1:
                    ds.TemporalPositionIdentifier=phase+1;ds.NumberOfTemporalPositions=case.phases
                ds.InstanceNumber=shape[0]-z; ds.RescaleSlope=slope; ds.RescaleIntercept=intercept
                if case.modality=='CT': ds.RescaleType='HU'
                if z==4:
                    if case.defect=='orientation': ds.ImageOrientationPatient=[1,0,0,0,0,1]
                    if case.defect=='missing-position': del ds.ImagePositionPatient
                    if case.defect=='frame-of-reference': ds.FrameOfReferenceUID=uid('other-frame')
                if case.defect=='missing-spacing': del ds.PixelSpacing
                if case.defect=='zero-spacing': ds.PixelSpacing=[0,.5]
                if case.defect=='nan-spacing': ds.PixelSpacing=[float('nan'),.5]
                if case.defect=='nonorthogonal': ds.ImageOrientationPatient=[1,0,0,.1,1,0]
                ds.PixelData=stored.tobytes()
                if case.rle: ds.compress(RLELossless,generate_instance_uid=False)
                path=root/(f'{shape[0]-z:03}.dcm' if case.phases==1 else f'{shape[0]-z:03}-{phase}.dcm'); ds.save_as(path,enforce_file_format=True); paths.append(path)
                sources.append(dict(z=z,phase=phase,frame=None,path=path.name))
    if case.enhanced:
        ds=base(case.name+'enhanced')
        for k in ('ImageOrientationPatient','PixelSpacing','SliceThickness','SpacingBetweenSlices'): delattr(ds,k)
        ds.SharedFunctionalGroupsSequence=[item(
            PixelMeasuresSequence=[item(PixelSpacing=list(case.spacing[1:]),SliceThickness=1)],
            PlaneOrientationSequence=[item(ImageOrientationPatient=rotation[:,:2].T.ravel().tolist())],
            CTImageFrameTypeSequence=[item(FrameType=['ORIGINAL','PRIMARY','AXIAL','NONE'],
                PixelPresentation='MONOCHROME',VolumetricProperties='VOLUME')])]
        ds.DimensionOrganizationSequence=[item(DimensionOrganizationUID=uid(case.name+'dimensions'))]
        ds.DimensionIndexSequence=[item(DimensionOrganizationUID=ds.DimensionOrganizationSequence[0].DimensionOrganizationUID,
            DimensionIndexPointer=tag,FunctionalGroupPointer=0x00209111) for tag in (0x00209057,0x00209128)]
        ds.PerFrameFunctionalGroupsSequence=frames; ds.NumberOfFrames=len(frames); ds.PixelData=np.stack(data).tobytes()
        if case.rle: ds.compress(RLELossless,generate_instance_uid=False)
        path=root/'enhanced.dcm'; ds.save_as(path,enforce_file_format=True); paths.append(path)
    arrays={'affine':affine,'stored':raw}
    for phase,values in truth.items():
        arrays[f'pixels{phase}']=np.stack([v for z,v in sorted(values)])
    if case.modality=='PT':
        factor=1.
        if case.pet_units=='BQML' and not case.pet_missing:
            elapsed=1200 if case.midnight else 3600
            factor=70000/(350000000*2**(-elapsed/6586.2))
        arrays['display0']=arrays['pixels0']*factor
    np.savez_compressed(root/'truth.npz',**arrays)
    manifest=dict(schema=1,case=asdict(case),shape=shape,sources=sources,
        expected_volume=not(case.defect and case.defect!='duplicate-file') and not (case.phases>1 and not case.enhanced),
        unit='HU' if case.modality=='CT' else ('a.u.' if case.modality=='MR' else
             ('Bq/ml' if case.pet_missing else 'SUVbw')),
        files=[dict(path=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
    (root/'case.json').write_text(json.dumps(manifest,indent=2))
    return manifest


def sample_reference(pixels, indices):
    """Independent eight-corner scalar interpolation including missing support."""
    from itertools import product
    result=[]
    for point in indices:
        if np.any(point < -1e-6) or np.any(point > np.array(pixels.shape)-1+1e-6):
            result.append(np.nan); continue
        point=np.clip(point,0,np.array(pixels.shape)-1); low=np.floor(point).astype(int); fraction=point-low
        total=weight=0.
        for corner in product((0,1),repeat=3):
            idx=tuple(np.minimum(low+corner,np.array(pixels.shape)-1))
            w=float(np.prod(np.where(corner,fraction,1-fraction))); v=pixels[idx]
            if np.isfinite(v) and w>0: total+=w*v; weight+=w
        result.append(total/weight if weight else np.nan)
    return np.array(result)
