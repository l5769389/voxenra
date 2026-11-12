"""Pure, localized manual records shared by desktop and website generation."""
import re


def section_id(section, index):
    return section.get('id', f'step-{index + 1}')


def plain_text(text):
    return re.sub(r'\s+', ' ', str(text).replace('**', '').replace('`', '')).strip()


def section_records(chapters):
    records = []
    for chapter in chapters:
        for index, section in enumerate(chapter['sections']):
            records.append(dict(chapterId=chapter['id'], chapterTitle=str(chapter['title']),
                                sectionIndex=index, sectionId=section_id(section, index),
                                title=str(section['title']), text=plain_text(section['body'])))
    return records


def search_sections(chapters, query, limit=30):
    terms = query.casefold().split()
    if not terms:
        return []
    matches = []
    for record in section_records(chapters):
        title = (record['chapterTitle'] + ' ' + record['title']).casefold()
        body = record['text'].casefold()
        if not all(term in title + ' ' + body for term in terms):
            continue
        score = sum(3 for term in terms if term in title)
        position = min((body.index(term) for term in terms if term in body), default=0)
        start = max(0, position - 32)
        snippet = ('…' if start else '') + record['text'][start:start + 150]
        if start + 150 < len(record['text']):
            snippet += '…'
        matches.append((score, dict(record, snippet=snippet)))
    matches.sort(key=lambda item: -item[0])
    return [record for _, record in matches][:limit]


def chapter_neighbors(chapters, chapter_id):
    ids = [chapter['id'] for chapter in chapters]
    if chapter_id not in ids:
        return None, None
    index = ids.index(chapter_id)
    return (ids[index - 1] if index else None,
            ids[index + 1] if index + 1 < len(ids) else None)
