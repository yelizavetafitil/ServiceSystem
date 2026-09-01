document.querySelectorAll('.tabs').forEach(tabsEl => {
  tabsEl.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const panelId = tab.dataset.tab;
      const container = tabsEl.closest('.auth-card, .ticket-detail, .shell') || document;
      tabsEl.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      if (panelId === 'personal' || panelId === 'master') {
        document.getElementById('form-personal')?.classList.toggle('active', panelId === 'personal');
        document.getElementById('form-master')?.classList.toggle('active', panelId === 'master');
      } else {
        container.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.getElementById('panel-' + panelId)?.classList.add('active');
      }
    });
  });
});

document.querySelectorAll('.topbar-nav a').forEach(link => {
  if (link.pathname === window.location.pathname) link.classList.add('active');
});

document.querySelectorAll('.chapter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const iframe = document.querySelector('.video-player-wrap iframe');
    if (iframe) {
      const url = new URL(iframe.src.split('?')[0]);
      url.searchParams.set('start', btn.dataset.seek);
      iframe.src = url.toString();
    }
  });
});

let idleTimer;
function resetIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    window.location.href = '/logout';
  }, 60 * 60 * 1000);
}
['mousemove', 'keydown', 'click', 'scroll'].forEach(ev => document.addEventListener(ev, resetIdle, { passive: true }));
resetIdle();
