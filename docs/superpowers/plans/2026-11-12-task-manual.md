# Task-oriented Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver bilingual task guides, section-level search and coherent navigation in the offline manual and generated website.
**Architecture:** Keep the shared JSON/language catalog, add pure indexing helpers, and render the same task routes and section identities in Qt and static HTML.
**Tech Stack:** Python, JSON, PySide6/Qt Quick, static HTML/CSS/JavaScript.
**Spec:** docs/superpowers/specs/2026-11-12-task-manual-design.md (approved by user: 执行).

## Global Constraints

- Preserve all original chapter IDs, aliases, legacy step anchors and tutorial messageId bindings.
- Preserve other worktree edits; do not change algorithms, workspace format, versions, downloads or deploy.
- Deliver Chinese/English together; retain other locales with English fallback for new content.
- Keep safety/identity/source-file restrictions visible and render external text safely.

## Review Focus

- Existing deep links still locate the same instruction after adding task content.
- Search can find multi-word, Chinese and shortcut queries and actually position the selected section.
- Language changes do not retain stale search results or untranslated keys.
- Narrow pages, large text and long titles do not lose controls or overflow.
- New guides describe real controls and prerequisites without inventing successful analysis or AI setup.

### Task 1: Shared navigation and index contract
**Files:** core/manual_index.py; ui/manual_content.py; tests/test_manual_tasks.py.
**Interfaces:** section_id(section,index), search_sections(chapters,query,limit), chapter_neighbors(chapters,id). Localized records contain chapterId, chapterTitle, sectionIndex, sectionId, title, snippet; routes reside in manual.json with message keys.
- [x] Write meaningful failing tests for multi-term section search, ordering, safe literal text and neighbor/anchor behavior.
- [x] Implement pure helpers and test them; preserve legacy step-N by original section order.

### Task 2: Bilingual task content
**Files:** help/manual.json, help/chapters/*.json, languages/zh-CN.json/en-US.json; resource declarations if needed.
**Interfaces:** Task routes use chapter IDs; chapter metadata includes localized prerequisites and outcome. New guide IDs are point-mtf, ramp-fwhm, qa-water, qa-noise, qa-air, ai-setup, shortcuts.
- [x] Add complete task journeys, preserve original reference sections and old translations, improve all original chapter goals/prerequisites/outcomes.
- [x] Split crowded explanations using paragraphs; fix Analysis naming and add source links through structured external references.
- [x] Verify bilingual keys, resources, aliases, units and reference links.

### Task 3: Offline reading and search
**Files:** manual_tab_controller.py; OperationManual.qml; ManualNavigation.qml; tests/test_manual_tasks.py.
**Interfaces:** taskRoutes/searchResults/searchTotal, selectSection(chapterId,index), currentChapter previous/next and outline.
- [x] Add failing behavior tests for selecting a search result, clear/no-result and language changes.
- [x] Implement task routes, section results, page outline and previous/next controls.
- [x] Run existing manual/translation/GUI coverage and inspect actual narrow/wide rendering.

### Task 4: Website and integrated verification
**Files:** scripts/build_manual_site.py; docs/manual-site/manual.css/manual.js/product.css; tests/test_manual_tasks_site.py.
**Interfaces:** Embedded JSON search index generated from same chapter content; browser ranking matches Python helper. Stable chapter HTML URLs and step anchors stay intact.
- [x] Test legacy anchors, task links and actual browser search/clear/navigation behavior.
- [x] Implement task home, section search, readable guide structure, next/previous links and direct product tutorial links.
- [x] Build local preview; verify 375/768/1280/1920 layouts, images, keyboard, languages and relevant suites.
- [x] Fresh whole-change review; fix material issues, record validation/limitations and hand off without public deployment.
