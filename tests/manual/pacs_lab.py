"""Reproducible local Orthanc/dcm4chee lab. Uses synthetic DICOM only.

    uv run python tests/manual/pacs_lab.py prepare
    docker compose -f docker/pacs/compose.yaml up -d
    uv run python tests/manual/pacs_lab.py seed
    uv run python tests/manual/pacs_lab.py install-profiles
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, MRImageStorage, ExplicitVRLittleEndian

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "docker/pacs"
ARTIFACTS = LAB / "artifacts"
UID_ROOT = "1.2.826.0.1.3680043.10.5432.20260906"
PRIMARY_STUDY = UID_ROOT + ".1"
PRIMARY_SERIES = PRIMARY_STUDY + ".1"
MR_SERIES = PRIMARY_STUDY + ".2"


def read_env():
    return dict(line.split("=", 1) for line in (LAB / ".env").read_text().splitlines()
                if line and not line.startswith("#"))


def profiles():
    env = read_env()
    specs = [
        ("orthanc-open", "Lab Orthanc Open", "http://127.0.0.1:8042/dicom-web", "none", "", ""),
        ("orthanc-basic", "Lab Orthanc Basic", "http://127.0.0.1:8043/dicom-web", "basic", "pacs-lab", env["PACS_LAB_PASSWORD"]),
        ("orthanc-bearer", "Lab Orthanc Bearer", "http://127.0.0.1:8044/dicom-web", "bearer", "", env["PACS_LAB_BEARER_TOKEN"]),
        ("dcm4chee", "Lab dcm4chee", "http://127.0.0.1:8080/dcm4chee-arc/aets/DCM4CHEE/rs", "none", "", ""),
    ]
    return [{"key": key, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "qt-dicom-pacs-lab/" + key)),
             "name": name, "url": url, "auth": auth, "username": username, "secret": secret,
             "timeout": 15, "enabled": True} for key, name, url, auth, username, secret in specs]


def headers(profile):
    if profile["auth"] == "basic":
        data = (profile["username"] + ":" + profile["secret"]).encode()
        return {"Authorization": "Basic " + base64.b64encode(data).decode()}
    if profile["auth"] == "bearer":
        return {"Authorization": "Bearer " + profile["secret"]}
    return {}


def prepare():
    LAB.mkdir(parents=True, exist_ok=True)
    env_path = LAB / ".env"
    if not env_path.exists():
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            for key in ("PACS_LAB_PASSWORD", "PACS_LAB_BEARER_TOKEN", "PACS_LAB_DB_PASSWORD"):
                out.write(key + "=" + secrets.token_hex(16) + "\n")
    folder = ARTIFACTS / "source"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    for study in range(1, 24):
        for series in range(1, 24 if study == 1 else 2):
            count = 16 if (study, series) == (1, 1) else 2
            modality = "MR" if (study, series) == (1, 2) else "CT"
            yy, xx = np.mgrid[-1:1:64j, -1:1:64j]
            for instance in range(1, count + 1):
                sop = f"{UID_ROOT}.{study}.{series}.{instance}"
                meta = FileMetaDataset()
                meta.TransferSyntaxUID = ExplicitVRLittleEndian
                meta.MediaStorageSOPClassUID = MRImageStorage if modality == "MR" else CTImageStorage
                meta.MediaStorageSOPInstanceUID = sop
                path = folder / f"{study:02}-{series:02}-{instance:02}.dcm"
                ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
                ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, sop
                ds.StudyInstanceUID, ds.SeriesInstanceUID = f"{UID_ROOT}.{study}", f"{UID_ROOT}.{study}.{series}"
                ds.FrameOfReferenceUID = f"{UID_ROOT}.{study}.999"
                ds.SpecificCharacterSet = "ISO_IR 192"
                ds.PatientID = f"PACSLAB-{study:03}"
                ds.PatientName = "测试^患者" if study == 3 else f"PACS^DEMO{study:02}"
                ds.PatientBirthDate, ds.PatientSex = "20000101", "O"
                ds.AccessionNumber = f"LAB{study:04}"
                ds.StudyID = str(study)
                ds.StudyDate, ds.StudyTime = f"202608{study:02}", "120000"
                ds.SeriesDate, ds.SeriesTime = ds.StudyDate, ds.StudyTime
                ds.StudyDescription = f"PACS Lab Study {study:02}"
                ds.SeriesDescription = f"Synthetic {modality} volume {series:02}"
                ds.SeriesNumber, ds.InstanceNumber = series, instance
                ds.Modality, ds.ImageType = modality, ["ORIGINAL", "PRIMARY", "AXIAL"]
                ds.Rows = ds.Columns = 64
                ds.ImagePositionPatient = [-32, -32, (instance - 1) * 1.5]
                ds.ImageOrientationPatient, ds.PixelSpacing, ds.SliceThickness = [1, 0, 0, 0, 1, 0], [1, 1], 1.5
                ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
                ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
                ds.RescaleIntercept, ds.RescaleSlope, ds.WindowCenter, ds.WindowWidth = 0, 1, 100, 1200
                zz = (instance - (count + 1) / 2) / max(count / 2, 1)
                pixels = np.full((64, 64), -1000, dtype=np.int16)
                pixels[(xx / .75) ** 2 + (yy / .8) ** 2 + (zz / 1.2) ** 2 < 1] = 120 + series
                pixels[((xx - .2) / .2) ** 2 + (yy / .25) ** 2 + (zz / 1.1) ** 2 < 1] = 800
                ds.PixelData = pixels.tobytes()
                ds.save_as(path, enforce_file_format=True)
                manifest.append({"path": str(path.relative_to(ARTIFACTS)), "study": str(ds.StudyInstanceUID),
                                 "series": str(ds.SeriesInstanceUID), "sop": sop, "modality": modality,
                                 "pixelSha256": hashlib.sha256(pixels.tobytes()).hexdigest()})
    (ARTIFACTS / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Prepared synthetic data: 23 studies, 45 series, {len(manifest)} instances", flush=True)


def wait_ready(profile, timeout=240):
    deadline, last_notice = time.monotonic() + timeout, 0
    while time.monotonic() < deadline:
        try:
            request = Request(profile["url"] + "/studies?limit=1", headers={**headers(profile), "Accept": "application/dicom+json"})
            with urlopen(request, timeout=3) as response:
                if response.status in (200, 204):
                    print(profile["name"] + " ready", flush=True)
                    return
        except (OSError, HTTPError, URLError):
            pass
        if time.monotonic() - last_notice > 20:
            print("Waiting for " + profile["name"], flush=True)
            last_notice = time.monotonic()
        time.sleep(2)
    raise RuntimeError(profile["name"] + " did not become ready")


def seed():
    if not (ARTIFACTS / "manifest.json").exists():
        prepare()
    manifest = json.loads((ARTIFACTS / "manifest.json").read_text())
    boundary = "pacs-lab-stow-boundary"
    body = bytearray()
    for row in manifest:
        body.extend(("--" + boundary + "\r\nContent-Type: application/dicom\r\n\r\n").encode())
        body.extend((ARTIFACTS / row["path"]).read_bytes())
        body.extend(b"\r\n")
    body.extend(("--" + boundary + "--\r\n").encode())
    for profile in profiles():
        wait_ready(profile)
        # Bearer gateway shares the open Orthanc's database.
        if profile["key"] == "orthanc-bearer":
            continue
        request = Request(profile["url"] + "/studies", data=bytes(body), method="POST", headers={
            **headers(profile), "Content-Type": f'multipart/related; type="application/dicom"; boundary="{boundary}"',
            "Accept": "application/dicom+json"})
        try:
            with urlopen(request, timeout=120) as response:
                payload = response.read()
                if response.status != 200:
                    raise RuntimeError(f"STOW did not fully succeed: HTTP {response.status}")
                result = json.loads(payload)
                if result.get("00081198", {}).get("Value"):
                    raise RuntimeError("STOW reported failed SOP instances")
                print(f"Seeded {profile['name']}: {len(manifest)} instances", flush=True)
        except HTTPError as exc:
            raise RuntimeError(f"STOW failed for {profile['name']}: HTTP {exc.code}") from None


def install_profiles():
    from PySide6.QtCore import QCoreApplication, QStandardPaths
    from voxplane.pacs.config import PacsConfigStore, PacsProfile
    app = QCoreApplication.instance() or QCoreApplication([])
    app.setOrganizationName("VoxPlane")
    app.setApplicationName("VoxPlane")
    path = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / "pacs.json"
    store = PacsConfigStore(path)
    existing, default, local, pacs = store.load()
    new = [PacsProfile.from_dict(row) for row in profiles()]
    ids = {p.id for p in new}
    existing = [p for p in existing if p.id not in ids] + new
    store.save(existing, default or new[0].id, local, True)
    print(f"Installed 4 local profiles in {path} (passwords/tokens remain session-only)")



def check_restart():
    from voxplane.pacs.client import DicomWebClient, PacsError
    from voxplane.pacs.config import PacsProfile
    profile = next(p for p in profiles() if p["key"] == "orthanc-basic")
    command = ["docker", "--context", "orbstack", "compose", "-f", str(LAB / "compose.yaml")]
    disconnected = False
    try:
        subprocess.run(command + ["stop", "orthanc-basic"], check=True)
        try:
            DicomWebClient(PacsProfile.from_dict(profile)).test_connection()
        except PacsError:
            disconnected = True
        assert disconnected, "Stopped PACS unexpectedly reachable"
        print("PASS: stopped PACS reports connection failure", flush=True)
    finally:
        subprocess.run(command + ["start", "orthanc-basic"], check=True)
    wait_ready(profile, 60)
    client = DicomWebClient(PacsProfile.from_dict(profile))
    assert len(client.studies({"PatientID": "PACSLAB-*"}, 0, 100)) == 23
    (ARTIFACTS / "restart-check.json").write_text(json.dumps({
        "service": "orthanc-basic", "disconnectReported": disconnected,
        "reconnected": True, "studiesRetained": 23}, indent=2))
    print("PASS: restart preserves all 23 studies", flush=True)


def launch():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication
    from importlib.resources import files
    from voxplane.app import bind_controller
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName("VoxPlane")
    QCoreApplication.setApplicationName("VoxPlane")
    engine = bind_controller()
    # Explicit lab launcher supplies lab credentials to this session only.
    for profile in profiles():
        if not engine.app_controller.pacsController.saveProfile(profile):
            raise RuntimeError(engine.app_controller.pacsController.message)
    engine.load(files("voxplane").joinpath("qml/Main.qml"))
    if not engine.rootObjects():
        raise RuntimeError("Failed to load application")
    app.aboutToQuit.connect(engine.app_controller.shutdown)
    try:
        return app.exec()
    finally:
        engine.app_controller.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "seed", "install-profiles", "check-restart", "launch"])
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "seed":
        seed()
    elif args.command == "install-profiles":
        install_profiles()
    elif args.command == "check-restart":
        check_restart()
    else:
        sys.exit(launch())
