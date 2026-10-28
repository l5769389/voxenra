"""Isolated OrbStack DIMSE lab: prepare, seed, check-restart, launch.

All data is synthetic. No change to the existing DICOMweb lab or user settings.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pydicom
from pynetdicom import AE
from pydicom.uid import CTImageStorage, MRImageStorage, ExplicitVRLittleEndian

from qt_dicom_viewer.pacs.config import PacsProfile
from qt_dicom_viewer.pacs.dimse_client import DimseClient
from qt_dicom_viewer.pacs.client import PacsError

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / 'docker/pacs-dimse'
ARTIFACTS = LAB / 'artifacts'
UID_ROOT = '1.2.826.0.1.3680043.10.5432.20260906'
PRIMARY_STUDY = UID_ROOT + '.1'
PRIMARY_SERIES = PRIMARY_STUDY + '.1'
MR_SERIES = PRIMARY_STUDY + '.2'
COMPOSE = ['docker', '--context', 'orbstack', 'compose', '-f', str(LAB / 'compose.yaml')]


def profiles():
    return [dict(key=key, id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'voxenra-dimse/' + key)),
                 name='DIMSE Lab ' + key, protocol='dimse', host='127.0.0.1',
                 port=port, called_ae=ae, calling_ae='VOXENRA',
                 listen_host='0.0.0.0', listen_port=11113, timeout=30)
            for key, port, ae in [('Orthanc', 14242, 'ORTHANC'), ('dcm4chee', 14243, 'DCM4CHEE')]]


def prepare():
    # Reuse the existing synthetic fixture, with a separate output directory.
    from manual import pacs_lab
    pacs_lab.LAB, pacs_lab.ARTIFACTS = LAB, ARTIFACTS
    pacs_lab.prepare()


def wait_ready(profile, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            DimseClient(PacsProfile.from_dict(profile)).test_connection()
            print(profile['name'] + ' C-ECHO ready', flush=True)
            return
        except PacsError:
            time.sleep(2)
    raise RuntimeError(profile['name'] + ' did not become ready')


def seed():
    manifest = json.loads((ARTIFACTS / 'manifest.json').read_text())
    for profile in profiles():
        wait_ready(profile)
        ae = AE(ae_title='VOXENRA')
        ae.add_requested_context(CTImageStorage, ExplicitVRLittleEndian)
        ae.add_requested_context(MRImageStorage, ExplicitVRLittleEndian)
        association = ae.associate(profile['host'], profile['port'], ae_title=profile['called_ae'])
        try:
            assert association.is_established
            for row in manifest:
                status = association.send_c_store(pydicom.dcmread(ARTIFACTS / row['path']))
                assert status and status.Status == 0, status
            print(f"Seeded {profile['name']}: {len(manifest)} instances via C-STORE", flush=True)
        finally:
            association.release()
            ae.shutdown()


def check_restart():
    profile = profiles()[0]
    try:
        subprocess.run(COMPOSE + ['stop', 'orthanc'], check=True)
        try:
            DimseClient(PacsProfile.from_dict(profile)).test_connection()
        except PacsError:
            print('PASS: stopped PACS reports a connection failure', flush=True)
        else:
            raise AssertionError('Stopped PACS unexpectedly reachable')
    finally:
        subprocess.run(COMPOSE + ['start', 'orthanc'], check=True)
    wait_ready(profile, 60)
    assert len(DimseClient(PacsProfile.from_dict(profile)).studies({}, 0, 100)) == 23
    print('PASS: reconnect and all 23 studies retained', flush=True)


def launch():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QTimer, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName('VoxenraDIMSELab')
    QCoreApplication.setApplicationName('VoxenraDIMSELab')
    provider = DicomImageProvider()
    controller = AppController(provider, settings_path=False,
        pacs_config_path=ARTIFACTS / 'pacs.json', pacs_import_root=ARTIFACTS / 'imports')
    for profile in profiles():
        existing = next((p for p in controller.pacsController.profiles if p['name'] == profile['name']), None)
        assert controller.pacsController.saveProfile(profile | {'id': existing['id'] if existing else ''})
    engine = QQmlApplicationEngine()
    engine.addImageProvider('dicom', provider)
    engine.addImageProvider('navigation', SvgIconProvider())
    engine.rootContext().setContextProperty('appController', controller)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'src/qt_dicom_viewer/qml/Main.qml')))
    assert engine.rootObjects()
    def record():
        workspace = controller.workspaceController
        current = workspace.activeViewport
        state = dict(activeTabType=workspace.activeTabType, busy=controller.pacsController.busy,
                     error=controller.pacsController.isError, message=controller.pacsController.message,
                     seriesCount=len(controller.panelController.seriesItems))
        if current is not None:
            state['viewport'] = dict(sliceIndex=current.sliceIndex, sliceCount=current.sliceCount,
                                     imageSource=current.imageSource,
                                     seriesUid=current.viewport_config.series_meta.series_uid)
        (ARTIFACTS / 'native-state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2))
    timer = QTimer()
    timer.timeout.connect(record)
    timer.start(500)
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == '__main__':
    # Permit direct script execution and pytest's manual package import.
    sys.path.insert(0, str(ROOT / 'tests'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'seed', 'check-restart', 'launch'])
    command = parser.parse_args().command
    sys.exit(globals()[command.replace('-', '_')]() or 0)
