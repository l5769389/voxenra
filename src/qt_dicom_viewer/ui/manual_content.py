"""Load categorized offline help and retain stable translation IDs."""
import json
import re
from html import escape
from functools import lru_cache
from importlib.resources import files

from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import localize


@lru_cache(maxsize=1)
def manual_content():
    root = files("qt_dicom_viewer").joinpath("qml/assets/help")
    content = json.loads(root.joinpath("manual.json").read_text(encoding="utf-8"))
    content["chapters"] = [chapter for category in content["categories"]
                           for chapter in json.loads(root.joinpath(category["file"]).read_text(encoding="utf-8"))]
    tutorials = json.loads(root.joinpath('tutorials.json').read_text(encoding='utf-8'))
    for category in content['categories']:
        category['title'] = _msg('manual.category.' + category['id'])
    for chapter in content['chapters']:
        prefix = 'manual.' + chapter['id'] + '.'
        for field in ('title', 'summary', 'caption'):
            if field in chapter: chapter[field] = _msg(prefix + field)
        for index, section in enumerate(chapter['sections']):
            section_id = section.get('messageId', prefix + f'section{index}')
            for field in ('title', 'body'):
                section[field] = _msg(section_id + '.' + field)
            section['tutorials'] = [item for item in tutorials
                                    if item['chapter'] == chapter['id'] and item['section'] == section_id]
        for index, shortcut in enumerate(chapter.get('shortcuts', [])):
            shortcut['label'] = _msg(shortcut.get('messageId', prefix + f'shortcut{index}'))
    return content


def manual_rich_text(text):
    """Only emphasis and inline keys are markup; never interpret embedded HTML."""
    parts = re.split(r"(\*\*[^\n*]+\*\*|`[^\n`]+`)", localize(text))
    return "".join(
        "<b>" + escape(part[2:-2]) + "</b>" if re.fullmatch(r"\*\*[^\n*]+\*\*", part)
        else "<b>" + escape(part[1:-1]) + "</b>" if re.fullmatch(r"`[^\n`]+`", part)
        else escape(part).replace("\n", "<br>")
        for part in parts
    )
