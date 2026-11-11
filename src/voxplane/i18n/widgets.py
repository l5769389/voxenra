"""App-owned widget text bindings; native file pickers translate on their next opening."""
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QTimer, QObject
from .messages import Message, JoinedMessage, localize, message


class TextBindings:
    def _bind(self, name, value):
        if not hasattr(self, '_texts'): self._texts = {}
        if isinstance(value, (Message, JoinedMessage)): self._texts[name] = value
        else: self._texts.pop(name, None)
        getattr(super(), name)(localize(value))

    def setText(self, value): self._bind('setText', value)
    def setAccessibleName(self, value): self._bind('setAccessibleName', value)
    def setWindowTitle(self, value): self._bind('setWindowTitle', value)
    def setToolTip(self, value): self._bind('setToolTip', value)
    def setPlaceholderText(self, value): self._bind('setPlaceholderText', value)
    def setInformativeText(self, value): self._bind('setInformativeText', value)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange:
            self.retranslate()

    def retranslate(self):
        for setter, source in getattr(self, '_texts', {}).items():
            getattr(super(), setter)(localize(source))
        if isinstance(self, QtWidgets.QMessageBox): self._translate_buttons()


def _text_widget(base):
    class BoundWidget(TextBindings, base):
        def __init__(self, *args, **kwargs):
            super().__init__(*(localize(arg) for arg in args), **kwargs)
            if args and isinstance(args[0], (Message, JoinedMessage)):
                self._texts = {'setText': args[0]}
    BoundWidget.__name__ = base.__name__
    return BoundWidget


QLabel = _text_widget(QtWidgets.QLabel)
QPushButton = _text_widget(QtWidgets.QPushButton)
QCheckBox = _text_widget(QtWidgets.QCheckBox)
QLineEdit = _text_widget(QtWidgets.QLineEdit)


def set_dialog_button_hint(button, title, keys):
    """Keep the action name available independently of its visible keyboard hint."""
    caption = title + f" ({keys})" if keys else title
    button.setText(caption)
    button.setAccessibleName(title)
    button.setAccessibleDescription(keys)


class QDialog(TextBindings, QtWidgets.QDialog):
    pass


class _ButtonCaptionFilter(QObject):
    def eventFilter(self, watched, event):
        if event.type() in (QEvent.LanguageChange, QEvent.StyleChange):
            self.parent()._button_text_timer.start(0)
        return False


class QMessageBox(TextBindings, QtWidgets.QMessageBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*(localize(arg) for arg in args), **kwargs)
        self._texts = {}
        if len(args) >= 3:
            self._texts = {'setWindowTitle': args[1], 'setText': args[2]}
        self._button_text_timer = QTimer(self)
        self._button_text_timer.setSingleShot(True)
        self._button_text_timer.timeout.connect(self._translate_buttons)
        self._button_box = self.findChild(QtWidgets.QDialogButtonBox)
        self._caption_filter = _ButtonCaptionFilter(self)
        if self._button_box is not None:
            self._button_box.installEventFilter(self._caption_filter)
        self._translate_buttons()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange and hasattr(self, '_button_text_timer'):
            # QDialogButtonBox may reset its standard labels in a queued event.
            self._button_text_timer.start(0)

    def _button_message_ids(self):
        role = QtWidgets.QMessageBox.StandardButton
        return {role.Save: 'text.1092', role.Discard: 'common.dontSave', role.Cancel: 'text.0539',
                role.Close: 'text.0621', role.Ok: 'common.ok', role.Yes: 'common.yes',
                role.No: 'common.no', role.Retry: 'common.retry'}

    def _translate_buttons(self):
        for role, key in self._button_message_ids().items():
            button = self.button(role)
            if button is not None:
                hints = []
                if button == self.defaultButton():
                    hints.append('Enter')
                if role == QtWidgets.QMessageBox.StandardButton.Cancel:
                    hints.append('Esc')
                set_dialog_button_hint(button, localize(message(key)), ' / '.join(hints))

    def setDefaultButton(self, button):
        super().setDefaultButton(button)
        self._translate_buttons()

    def setStandardButtons(self, buttons):
        super().setStandardButtons(buttons)
        self._translate_buttons()

    @staticmethod
    def question(parent, title, text, buttons=QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                 defaultButton=QtWidgets.QMessageBox.StandardButton.NoButton):
        # Qt's static helper would construct an unbound base QMessageBox.
        dialog = QMessageBox(QtWidgets.QMessageBox.Icon.Question, title, text, buttons, parent)
        if defaultButton != QtWidgets.QMessageBox.StandardButton.NoButton:
            dialog.setDefaultButton(defaultButton)
        try:
            return QtWidgets.QMessageBox.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()


class QFileDialog(QtWidgets.QFileDialog):
    @staticmethod
    def _choose(method, args, kwargs):
        from pathlib import Path
        from voxplane.settings.dialog_locations import current_locations, location_key
        history = current_locations()
        caption = args[1] if len(args) > 1 else kwargs.get('caption', '')
        key = location_key(caption)
        args = list(args)
        if history is not None and key:
            initial = str(localize(args[2] if len(args) > 2 else kwargs.get('dir', '')))
            directory = history.directory(key, initial)
            if method == 'getSaveFileName' and initial and not Path(initial).is_dir():
                directory = str(Path(directory) / Path(initial).name)
            if len(args) > 2:
                args[2] = directory
            else:
                kwargs['dir'] = directory
        result = getattr(QtWidgets.QFileDialog, method)(*(localize(v) for v in args), **kwargs)
        if history is not None and key:
            selection = result if method == 'getExistingDirectory' else result[0]
            if isinstance(selection, list):
                selection = selection[0] if selection else ''
            history.remember(key, selection, directory=method == 'getExistingDirectory')
        return result

    @staticmethod
    def getSaveFileName(*args, **kwargs):
        return QFileDialog._choose('getSaveFileName', args, kwargs)
    @staticmethod
    def getOpenFileName(*args, **kwargs):
        return QFileDialog._choose('getOpenFileName', args, kwargs)
    @staticmethod
    def getOpenFileNames(*args, **kwargs):
        return QFileDialog._choose('getOpenFileNames', args, kwargs)
    @staticmethod
    def getExistingDirectory(*args, **kwargs):
        return QFileDialog._choose('getExistingDirectory', args, kwargs)
