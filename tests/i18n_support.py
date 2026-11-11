"""Component-only QML scenes use the same bundled default translator as the app."""
from PySide6.QtCore import QObject
from voxplane.ui.controller.language_controller import JsonTranslator
from voxplane.i18n.messages import builtin


def install_default_language(app):
    if hasattr(app, '_default_test_translator'): return
    owner = QObject(app)
    owner.messages = builtin()['messages']
    translator = JsonTranslator(owner)
    app.installTranslator(translator)
    app._default_test_translator = owner, translator
