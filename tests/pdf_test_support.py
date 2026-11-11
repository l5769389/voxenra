"""Language coverage without eagerly loading the PDF rendering modules."""
import sys

import pytest

from voxplane.i18n.messages import builtin


@pytest.fixture(params=['en-US', 'zh-CN'])
def report_language(request, qt_app):
    # Windows offscreen uses FreeType and lacks native CJK font fallback.
    # Keep all report-content assertions in English there; the Windows native
    # release stage runs these same cases in both languages without this skip.
    if request.param == 'zh-CN' and sys.platform == 'win32' and qt_app.platformName() == 'offscreen':
        pytest.skip('Chinese PDF glyph coverage runs against the native Windows font database')
    return request.param, builtin(request.param)['messages']
