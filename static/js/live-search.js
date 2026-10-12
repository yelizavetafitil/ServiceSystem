(function () {
  const DEBOUNCE_MS = 280;

  document.querySelectorAll('.live-search-results, [data-live-search-list]').forEach(function (el) {
    el.style.minHeight = '';
    delete el.dataset.liveSearchLocked;
  });

  function debounce(fn) {
    let t;
    return function () {
      clearTimeout(t);
      const args = arguments;
      const self = this;
      t = setTimeout(function () {
        fn.apply(self, args);
      }, DEBOUNCE_MS);
    };
  }

  function setStatus(root, text) {
    const el = root.querySelector('.live-search-status');
    if (!el) return;
    el.textContent = text || '\u00a0';
    if (text) el.removeAttribute('data-empty');
    else el.setAttribute('data-empty', '1');
  }

  function collectParams(root) {
    const params = new URLSearchParams();
    const input = root.querySelector('.live-search-input');
    const q = (input && input.value.trim()) || '';
    if (q) params.set('q', q);
    root.querySelectorAll('[data-live-search-field]').forEach(function (field) {
      const name = field.getAttribute('name') || field.dataset.liveSearchField;
      if (!name) return;
      const val = (field.value || '').trim();
      if (val) params.set(name, val);
    });
    return { q, params };
  }

  var FILTER_PARAM_KEYS = ['q', 'org', 'user_id', 'action'];

  function applyFilterParams(url, params) {
    FILTER_PARAM_KEYS.forEach(function (k) {
      if (params.has(k)) url.searchParams.set(k, params.get(k));
      else url.searchParams.delete(k);
    });
  }

  function syncHistory(root, params) {
    if (root.dataset.liveSearchHistory !== '1') return;
    const base = root.dataset.url || window.location.pathname;
    const u = new URL(base, window.location.origin);
    applyFilterParams(u, params);
    window.history.replaceState({}, '', u.pathname + u.search);
  }

  function updateExportVcfLabel(count) {
    document.querySelectorAll('[data-live-search-export-vcf]').forEach(function (link) {
      link.textContent =
        count > 0 ? 'Скачать контакты (' + count + ')' : 'Скачать контакты (фильтр)';
    });
  }

  function syncLinkedHrefs(root, params) {
    const sel = root.dataset.liveSearchLinks;
    if (!sel) return;
    document.querySelectorAll(sel).forEach(function (link) {
      try {
        const u = new URL(link.getAttribute('href'), window.location.origin);
        applyFilterParams(u, params);
        link.setAttribute('href', u.pathname + u.search);
      } catch (_) {
        /* ignore */
      }
    });
  }

  function initFetch(root) {
    const targetSel = root.dataset.target;
    const target = targetSel ? document.querySelector(targetSel) : null;
    const input = root.querySelector('.live-search-input');
    if (!target || !input) return;

    const baseUrl = root.dataset.url || root.querySelector('form')?.action || window.location.pathname;
    let seq = 0;

    async function run() {
      const { params } = collectParams(root);
      syncHistory(root, params);
      syncLinkedHrefs(root, params);

      const fetchParams = new URLSearchParams(params);
      fetchParams.set('partial', '1');

      const id = ++seq;
      target.classList.add('live-search-results--loading');
      setStatus(root, 'Поиск…');

      try {
        const resp = await fetch(baseUrl + '?' + fetchParams.toString(), {
          headers: { Accept: 'text/html' },
          credentials: 'same-origin',
        });
        if (!resp.ok) throw new Error(String(resp.status));
        const html = await resp.text();
        if (id !== seq) return;
        target.innerHTML = html;
        target.style.minHeight = '';
        delete target.dataset.liveSearchLocked;
        const count = target.querySelectorAll('[data-live-search-item]').length;
        const q = (input.value || '').trim();
        if (!q && !params.get('org') && !params.get('user_id') && !params.get('action')) {
          setStatus(root, '');
        } else {
          setStatus(root, count ? 'Найдено: ' + count : 'Ничего не найдено');
        }
        updateExportVcfLabel(count);
      } catch (_) {
        if (id !== seq) return;
        setStatus(root, 'Не удалось обновить список.');
      } finally {
        if (id === seq) target.classList.remove('live-search-results--loading');
      }
    }

    input.addEventListener('input', debounce(run));
    root.querySelectorAll('[data-live-search-field]').forEach(function (field) {
      field.addEventListener('change', run);
    });
    root.querySelector('.live-search-reset')?.addEventListener('click', function () {
      input.value = '';
      root.querySelectorAll('[data-live-search-field]').forEach(function (field) {
        field.value = '';
      });
      run();
      input.focus();
    });
    root.querySelector('form')?.addEventListener('submit', function (e) {
      e.preventDefault();
      run();
    });

    const { params } = collectParams(root);
    syncLinkedHrefs(root, params);
    if (root.dataset.liveSearchLinks) {
      const n = document.querySelectorAll(
        (root.dataset.target || '') + ' [data-live-search-item]'
      ).length;
      updateExportVcfLabel(n);
    }
  }

  function initFilter(root) {
    const input = root.querySelector('.live-search-input');
    const list = root.querySelector('[data-live-search-list]');
    if (!input || !list) return;

    const emptyEl = root.querySelector('.live-search-empty');

    function run() {
      list.style.minHeight = '';
      delete list.dataset.liveSearchLocked;
      const q = input.value.trim().toLowerCase();
      let visible = 0;
      list.querySelectorAll('.live-search-item').forEach(function (row) {
        const hay = (row.getAttribute('data-search-text') || row.textContent || '').toLowerCase();
        const show = !q || hay.includes(q);
        row.hidden = !show;
        if (show) visible += 1;
      });
      root.querySelectorAll('.live-search-empty-row').forEach(function (row) {
        row.hidden = visible > 0;
      });
      if (emptyEl) emptyEl.hidden = visible > 0;
      if (!q) setStatus(root, '');
      else setStatus(root, visible ? 'Найдено: ' + visible : 'Ничего не найдено');
    }

    input.addEventListener('input', debounce(run));
    root.querySelector('.live-search-reset')?.addEventListener('click', function () {
      input.value = '';
      run();
      input.focus();
    });
  }

  document.querySelectorAll('.live-search-root[data-mode="fetch"]').forEach(initFetch);
  document.querySelectorAll('.live-search-root[data-mode="filter"]').forEach(initFilter);
})();
