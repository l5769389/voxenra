"""Reading-task priorities; independent of catalog order and recent clicks."""
from .dicom_models import TabType


def toolbar_groups(tab_type, modality, is_color, tools):
    available = {item['toolType'] for item in tools if item.get('available', True)}
    common = ['window', 'scroll', 'pan', 'zoom']
    primary = ['measure', 'mpr-layout', 'play']
    if tab_type == TabType.THREE_D:
        common = ['volume-rotate', 'pan', 'zoom', 'play' if 'play' in available else 'window']
        primary = ['volume-preset', 'volume-direction', 'mpr-layout' if 'mpr-layout' in available else 'volume-crop']
    elif tab_type == TabType.PETCT_FUSION:
        common = ['ct-window', 'pet-window', 'pan', 'zoom']
        primary = ['pseudocolor', 'fusion-blend', 'measure']
    elif tab_type == TabType.MONTAGE:
        common = ['window', 'pan', 'zoom']
        primary = ['rotate', 'pseudocolor']
    else:
        if tab_type == TabType.FOUR_D:
            common = ['window', 'play', 'pan', 'zoom']
        if tab_type in (TabType.MPR, TabType.FOUR_D, TabType.COMPARE_MPR):
            primary = ['measure', 'segmentation', 'mip']
        if modality.upper() == 'PT':
            primary = ['pseudocolor', 'measure', 'segmentation' if tab_type in (TabType.MPR, TabType.FOUR_D) else 'mpr-layout']
        if is_color:
            common = ['scroll', 'pan', 'zoom', 'rotate']
            primary = ['measure', 'annotate', 'mpr-layout']
    return {key: [tool for tool in choices if tool in available]
            for key, choices in [('common', common), ('primary', primary)]}
