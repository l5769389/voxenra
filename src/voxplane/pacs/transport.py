"""Select a transport without introducing DIMSE into DICOMweb connections."""
from .client import DicomWebClient


def create_client(profile, cancel=None):
    if profile.protocol == 'dimse':
        from .dimse_client import DimseClient
        return DimseClient(profile, cancel)
    return DicomWebClient(profile, cancel)
