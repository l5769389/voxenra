"""Bounded, plain-text update summaries from bilingual GitHub release notes.

Only our two documented headings form the publishing contract. Legacy headings
are accepted for display, but new releases must pass the stricter validator.
No remote markup or resource is rendered by the application.
"""
from __future__ import annotations

import html
import re

SUMMARY_HEADINGS = {'zh': '更新摘要', 'en': 'Update summary'}
MAX_ITEMS = 6
_HEADING = re.compile(r'^#{1,6}\s+(.+?)\s*#*\s*$')
_BULLET = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)')


def _sections(notes: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [('', [])]
    # Releases are already bounded by the API parser. Keep this pure helper safe
    # when used by scripts or on independently supplied text, too.
    for line in notes[:32000].splitlines():
        match = _HEADING.match(line.strip())
        if match:
            sections.append((match[1].casefold(), []))
        else:
            sections[-1][1].append(line)
    return sections


def _plain(text: str) -> str:
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = text.replace('**', '').replace('__', '').replace('`', '')
    return ' '.join(html.unescape(text).split()).strip()


def summarize_release_notes(notes: str, locale: str) -> str:
    sections = _sections(notes)
    language = 'zh' if locale.lower().startswith('zh') else 'en'
    candidates = ([SUMMARY_HEADINGS[language].casefold()]
                  + (['新增与改进', '更新内容'] if language == 'zh'
                     else ['english summary', "what’s new", "what's new", 'highlights'])
                  + [SUMMARY_HEADINGS['en' if language == 'zh' else 'zh'].casefold(),
                     '新增与改进', 'english summary'])
    lines = next((body for heading in candidates for title, body in sections
                  if title == heading and any(line.strip() for line in body)), None)
    if lines is None:
        # Unknown legacy format: only the first prose/list section, never append
        # every later installation/validation/language section to the dialog.
        lines = next((body for _, body in sections if any(line.strip() for line in body)), [])
    items: list[str] = []
    has_bullets = any(_BULLET.match(line) for line in lines)
    pending = ''
    fenced = False
    for line in lines:
        if line.strip().startswith(('```', '~~~')):
            fenced = not fenced
            continue
        if fenced:
            continue
        bullet = _BULLET.match(line)
        if bullet or not line.strip():
            if pending:
                items.append(pending)
            pending = bullet[1] if bullet else ''
        elif not has_bullets or (pending and line[:1].isspace()):
            pending += ' ' + line.strip()
    if pending:
        items.append(pending)
    items = [clean for item in items if (clean := _plain(item))]
    # Legacy notes may contain whole paragraphs. Retain a bounded excerpt and
    # offer the complete release page; new summaries never reach this limit.
    return '\n\n'.join('• ' + (item if len(item) <= 300 else item[:299].rstrip() + '…')
                       for item in items[:MAX_ITEMS])


def validate_release_notes(notes: str) -> list[str]:
    errors = []
    sections = _sections(notes)
    for language, heading in SUMMARY_HEADINGS.items():
        matches = [body for title, body in sections if title == heading.casefold()]
        if len(matches) != 1 or notes.splitlines().count('## ' + heading) != 1:
            errors.append(f'Expected exactly one "## {heading}" section.')
            continue
        lines = [line.strip() for line in matches[0] if line.strip()]
        limit = 80 if language == 'zh' else 180
        if not 1 <= len(lines) <= MAX_ITEMS:
            errors.append(f'{heading}: use 1–{MAX_ITEMS} one-line bullet items.')
        for line in lines:
            if not line.startswith('- ') or len(line[2:]) > limit or not line[2:].strip():
                errors.append(f'{heading}: each item must start with "- " and contain 1–{limit} characters.')
            if any(token in line[2:] for token in ('*', '`', '[', ']', '<', '>', '#', '__', 'http://', 'https://')):
                errors.append(f'{heading}: use plain text without markup or links.')
    return errors
