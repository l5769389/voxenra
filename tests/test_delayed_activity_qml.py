"""Delayed loading feedback remains safe while its QML children are destroyed."""
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlProperty
from PySide6.QtTest import QTest
import pytest

from test_dicom_tags import qt_app, wait_until


@pytest.fixture
def activity(qt_app):
    engine = QQmlEngine()
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    path = Path(__file__).resolve().parents[1] / 'src/voxplane/qml/components/DelayedActivity.qml'
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    root = component.create()
    assert root is not None, component.errors()
    root.setProperty('delayMs', 40)
    yield root, warnings
    root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_activity_delay_restarts_for_each_request(activity):
    root, warnings = activity
    root.setProperty('active', True)
    assert not root.property('showing')
    wait_until(lambda: root.property('showing'))
    root.setProperty('activityKey', 'next request')
    assert not root.property('showing')
    wait_until(lambda: root.property('showing'))
    root.setProperty('active', False)
    QTest.qWait(60)
    assert not root.property('showing')
    assert not warnings, warnings


def test_activity_changes_after_timer_destruction_clear_feedback(activity):
    root, warnings = activity
    root.setProperty('active', True)
    wait_until(lambda: root.property('showing'))
    timer = QQmlProperty.read(root, 'timer')
    timer.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert QQmlProperty.read(root, 'timer') is None
    # Page bindings can still change after the child timer is cleared on teardown.
    root.setProperty('activityKey', 'detached page')
    assert not root.property('elapsed')
    root.setProperty('active', False)
    root.setProperty('active', True)
    assert not root.property('showing')
    assert not warnings, warnings
