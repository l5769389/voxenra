"""Protocol profile validation, migration and connection-feedback isolation."""
import json
import pytest
from qt_dicom_viewer.pacs.config import PacsProfile, PacsConfigStore
from qt_dicom_viewer.ui.controller.pacs_controller import PacsController
from test_dicom_tags import qt_app


def dimse_profile(**overrides):
    return dict(name="Local DIMSE", protocol="dimse", host="127.0.0.1", port=4242,
                called_ae="ORTHANC", calling_ae="VOXENRA", listen_host="127.0.0.1",
                listen_port=11112, **overrides)


def test_old_web_profile_and_dimse_roundtrip(tmp_path):
    web = PacsProfile.from_dict(dict(name="Web", url="http://localhost:8042/dicom-web"))
    assert getattr(web, "protocol", None) == "dicomweb"
    dimse = PacsProfile.from_dict(dimse_profile())
    store = PacsConfigStore(tmp_path / "pacs.json")
    store.save([web, dimse], dimse.id, True, True)
    profiles, default, local, pacs = store.load()
    assert profiles == [web, dimse] and default == dimse.id and local and pacs
    assert profiles[1].called_ae == "ORTHANC" and profiles[1].listen_port == 11112
    assert "secret" not in (tmp_path / "pacs.json").read_text()


@pytest.mark.parametrize("key,bad", [
    ("protocol", "ftp"), ("host", "http://localhost"), ("host", ""),
    ("host", "bad host"), ("port", 0), ("port", 65536), ("port", True),
    ("port", 4.5), ("called_ae", ""), ("called_ae", "A" * 17),
    ("called_ae", "A\\B"), ("calling_ae", "中文"), ("listen_port", 0),
    ("listen_host", "not-an-ip"), ("timeout", True), ("timeout", 3.5),
])
def test_invalid_dimse_address_is_rejected(key, bad):
    data = dimse_profile(); data[key] = bad
    with pytest.raises(ValueError):
        PacsProfile.from_dict(data)


def test_protocol_switch_clears_http_credentials_and_connection_feedback(qt_app, tmp_path):
    c = PacsController(config_path=tmp_path / "pacs.json")
    try:
        assert c.saveProfile(dict(name="Peer", url="https://pacs.test", auth="basic",
                                  username="alice", secret="private"))
        old = c._profiles[0]
        assert c.saveProfile(dict(old.public_dict(), **{k:v for k,v in dimse_profile().items() if k != "name"}))
        new = c._profiles[0]
        assert new.auth == "none" and new.secret == "" and new.username == "" and new.url == ""
        assert not c._connection_matches(old, new)
        from dataclasses import replace
        assert not c._connection_matches(new, replace(new, called_ae="OTHER"))
        assert not c._connection_matches(new, replace(new, listen_port=11113))
    finally:
        c.shutdown()
