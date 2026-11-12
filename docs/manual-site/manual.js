const search = document.querySelector('#manual-search, #landing-search');
const toggle = document.querySelector('.menu-toggle');
const sidebar = document.querySelector('#sidebar');
const indexNode = document.querySelector('#manual-index');
if (search && indexNode) {
  const records = JSON.parse(indexNode.textContent);
  const results = document.querySelector('#search-results');
  const matches = results.querySelector('.search-matches');
  const status = results.querySelector('.search-status');
  const help = results.querySelector('.search-help');
  // Unicode case folding for the common special forms not handled by lowercase.
  const fold = text => text.toLowerCase().replaceAll('ß', 'ss').replaceAll('ς', 'σ');
  search.addEventListener('input', () => {
    const terms = fold(search.value).trim().split(/\s+/).filter(Boolean);
    const active = terms.length > 0;
    document.querySelectorAll('.nav-group, .home-directory, .start-routes').forEach(group => { group.hidden = active; });
    results.hidden = !active;
    matches.replaceChildren();
    help.hidden = true;
    status.textContent = '';
    if (!active) return;
    const found = records.map(record => {
      const title = fold(record.chapterTitle + ' ' + record.title);
      const body = fold(record.text);
      if (!terms.every(term => (title + ' ' + body).includes(term))) return null;
      const score = terms.filter(term => title.includes(term)).length * 3;
      const positions = terms.map(term => body.indexOf(term)).filter(pos => pos >= 0);
      const start = Math.max(0, (positions.length ? Math.min(...positions) : 0) - 32);
      const snippet = (start ? '…' : '') + record.text.slice(start, start + 150) + (start + 150 < record.text.length ? '…' : '');
      return {record, score, snippet};
    }).filter(Boolean).sort((a,b) => b.score - a.score);
    status.textContent = !found.length ? status.dataset.empty : found.length > 30 ? status.dataset.more : (document.documentElement.lang.startsWith('zh') ? `${found.length} 个步骤` : `${found.length} steps`);
    help.hidden = found.length !== 0;
    found.slice(0, 30).forEach(({record, snippet}) => {
      const link = document.createElement('a');
      link.className = 'search-hit';
      link.href = record.chapterId + '.html#' + record.sectionId;
      const title = document.createElement('strong');
      title.textContent = record.chapterTitle + ' · ' + record.title;
      const text = document.createElement('span');
      text.textContent = snippet;
      link.append(title, text);
      matches.append(link);
    });
  });
}
if (toggle && sidebar) {
  toggle.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
    if (open) search?.focus();
  });
  sidebar.addEventListener('click', event => {
    if (event.target.closest('a')) {
      sidebar.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const wasOpen = sidebar.classList.contains('open');
      sidebar.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
      if (wasOpen) toggle.focus();
    }
  });
}

// Keep the manual still until the reader requests an animation. Stop demos
// when they leave the viewport or tab, so several GIFs do not run unseen.
const demos = document.querySelectorAll('.tutorial');
function stopDemo(figure) {
  const image = figure.querySelector('img');
  const button = figure.querySelector('button');
  if (button.getAttribute('aria-pressed') !== 'true') return;
  image.src = image.dataset.still;
  button.setAttribute('aria-pressed', 'false');
  button.textContent = button.dataset.play;
}
const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
  entries.forEach(entry => { if (!entry.isIntersecting) stopDemo(entry.target); });
}) : null;
demos.forEach(figure => {
  const image = figure.querySelector('img');
  const button = figure.querySelector('button');
  button.hidden = false;
  button.addEventListener('click', () => {
    if (button.getAttribute('aria-pressed') === 'true') {
      stopDemo(figure);
      return;
    }
    demos.forEach(stopDemo);
    image.src = image.dataset.animation;
    button.setAttribute('aria-pressed', 'true');
    button.textContent = button.dataset.stop;
  });
  image.addEventListener('error', () => stopDemo(figure));
  observer?.observe(figure);
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) demos.forEach(stopDemo);
});
