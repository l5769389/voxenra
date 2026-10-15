const search = document.querySelector('#manual-search, #landing-search');
const toggle = document.querySelector('.menu-toggle');
const sidebar = document.querySelector('#sidebar');
if (search) {
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    document.querySelectorAll('.nav-group, .home-group').forEach(group => {
      let groupVisible = 0;
      group.querySelectorAll('a[data-search]').forEach(link => {
        const match = !query || link.dataset.search.includes(query);
        link.hidden = !match;
        if (match) { visible++; groupVisible++; }
      });
      group.hidden = groupVisible === 0;
    });
    document.querySelector('.no-results').hidden = visible !== 0;
    const routes = document.querySelector('.start-routes');
    if (routes) routes.hidden = !!query;
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
