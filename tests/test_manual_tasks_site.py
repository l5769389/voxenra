"""Task guides keep shared section identities and safe searchable content."""
import json
import re
from test_manual_site import SITE


def catalog():
    manifest = SITE.load_json(SITE.HELP / 'manual.json')
    chapters = [c for category in manifest['categories'] for c in SITE.load_json(SITE.HELP / category['file'])]
    return manifest, chapters


def test_task_pages_use_shared_section_index_and_metadata():
    manifest, chapters = catalog()
    for code, pack in [('zh','zh-CN'), ('en','en-US')]:
        messages = SITE.load_json(SITE.ASSETS / 'languages' / (pack + '.json'))
        # Language files include the message map, not just strings at top level.
        messages = messages.get('messages', messages)
        page = SITE.render_page(next(c for c in chapters if c['id']=='qa-air'), manifest['categories'], chapters, messages, code, manifest['aliases'])
        assert 'class="chapter-context"' in page
        assert 'class="chapter-pagination"' in page
        index = json.loads(re.search(r'<script id="manual-index" type="application/json">(.*?)</script>', page, re.S).group(1))
        record = next(r for r in index if r['chapterId']=='qa-air' and r['sectionIndex']==1)
        assert record['sectionId']=='step-2'
        assert record['text']
        assert 'id="search-results"' in page


def test_search_payload_escapes_script_termination():
    chapters = [dict(id='test',title='Test',summary='',sections=[dict(title='literal',body='</script><img onerror=x>')])]
    messages = {'manual.test.title':'Test','manual.test.section0.title':'literal','manual.test.section0.body':'</script><img onerror=x>'}
    markup = SITE.search_payload(chapters,messages)
    assert markup.count('</script>') == 1
    assert '<img' not in markup
    assert '\\u003c' in markup


def test_existing_deep_links_keep_their_original_section_content():
    from pathlib import Path
    manifest, chapters = catalog()
    originals=json.loads((Path(__file__).parent/'fixtures/manual_legacy_sections.json').read_text())
    current={c['id']:c for c in chapters}
    for key, ids in originals.items():
        actual=[s.get('messageId',f'manual.{key}.section{i}') for i,s in enumerate(current[key]['sections'])]
        assert actual[:len(ids)] == ids, key
    for alias in manifest['aliases'].values():
        assert alias['section'] < len(current[alias['chapter']]['sections'])
