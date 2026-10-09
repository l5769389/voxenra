"""Independent SUVbw definition for audit fixtures with explicit START correction.

Deliberately refuses ambiguous metadata; this is not a second product converter.
"""
from datetime import datetime, timedelta
import math


def suvbw_factor(ds):
    if str(ds.Units)=='GML' and str(getattr(ds,'SUVType','BW'))=='BW':return 1.
    if str(ds.Units)!='BQML' or str(ds.DecayCorrection)!='START':
        raise ValueError('Reference covers BQML, decay corrected to acquisition start only')
    weight=float(ds.PatientWeight);info=ds.RadiopharmaceuticalInformationSequence[0]
    dose=float(info.RadionuclideTotalDose);half_life=float(info.RadionuclideHalfLife)
    if not all(math.isfinite(x) and x>0 for x in (weight,dose,half_life)):
        raise ValueError('Missing or invalid SUVbw metadata')
    acquisition=str(getattr(ds,'AcquisitionDateTime',''))
    if not acquisition:acquisition=str(ds.AcquisitionDate)+str(ds.AcquisitionTime)
    def parse(text):return datetime.strptime(text.split('.')[0],'%Y%m%d%H%M%S')
    start=parse(acquisition)
    injection=str(getattr(info,'RadiopharmaceuticalStartDateTime',''))
    if injection:injected=parse(injection)
    else:
        injected=parse(start.strftime('%Y%m%d')+str(info.RadiopharmaceuticalStartTime))
        if injected>start:injected-=timedelta(days=1)
    elapsed=(start-injected).total_seconds()
    if elapsed<0:raise ValueError('Injection is after acquisition')
    return weight*1000/(dose*math.exp(-math.log(2)*elapsed/half_life))
