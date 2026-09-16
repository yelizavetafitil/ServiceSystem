(function () {
  window.__uploadsPending = false;

  const ALLOWED_EXT = ['.zpkg.zip', '.zip', '.rar', '.7z', '.log', '.txt', '.png', '.jpg', '.jpeg'];

  function csrfHeaders(extra) {
    const token = document.querySelector('meta[name=csrf-token]')?.content || '';
    return Object.assign({ 'X-CSRFToken': token }, extra || {});
  }

  function isAllowed(name) {
    const lower = name.toLowerCase();
    return ALLOWED_EXT.some(ext => lower.endsWith(ext));
  }

  function initUploadZone(opts) {
    const dropzone = document.getElementById(opts.zone || 'dropzone');
    const fileInput = document.getElementById(opts.input || 'file-input');
    const browseBtn = document.getElementById(opts.browse || 'browse-btn');
    const uploadList = document.getElementById(opts.list || 'upload-list');
    const hiddenField = document.getElementById(opts.hidden || 'attachment_ids');
    const context = opts.context || 'ticket';
    if (!dropzone) return;

    const ids = hiddenField?.value ? hiddenField.value.split(',').filter(Boolean) : [];
    const CHUNK = 8 * 1024 * 1024;
    const sessions = JSON.parse(localStorage.getItem('uploadSessions') || '{}');

    browseBtn?.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
    dropzone.addEventListener('drop', e => { e.preventDefault(); dropzone.classList.remove('drag'); handleFiles(e.dataTransfer.files); });
    fileInput?.addEventListener('change', () => handleFiles(fileInput.files));

    async function handleFiles(files) {
      window.__uploadsPending = true;
      if (typeof validateForm === 'function') validateForm();
      for (const file of files) {
        if (!isAllowed(file.name)) {
          alert('Недопустимый формат: ' + file.name + '. Разрешены: ' + ALLOWED_EXT.join(', '));
          continue;
        }
        await uploadFile(file);
      }
      window.__uploadsPending = false;
      if (hiddenField) hiddenField.value = ids.join(',');
      if (typeof validateForm === 'function') validateForm();
    }

    async function uploadFile(file) {
      const key = file.name + '_' + file.size;
      const row = document.createElement('div');
      row.className = 'upload-item';
      row.innerHTML = `<span>${file.name}</span><div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div><span class="pct">0%</span><span class="speed"></span>`;
      uploadList.appendChild(row);
      const fill = row.querySelector('.progress-fill');
      const pct = row.querySelector('.pct');
      const speedEl = row.querySelector('.speed');

      let sessionId = sessions[key];
      let offset = 0;
      if (sessionId) {
        const st = await fetch('/uploads/status/' + sessionId).then(r => r.json()).catch(() => ({}));
        offset = st.received || 0;
      }
      if (!sessionId || offset === 0) {
        const initRes = await fetch('/uploads/init', {
          method: 'POST',
          headers: csrfHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ filename: file.name, total_size: file.size, mime_type: file.type, context }),
        });
        const init = await initRes.json();
        if (!initRes.ok) {
          row.insertAdjacentHTML('beforeend', `<span class="upload-error">${init.error || 'Ошибка'}</span>`);
          return;
        }
        sessionId = init.session_id;
        sessions[key] = sessionId;
        localStorage.setItem('uploadSessions', JSON.stringify(sessions));
      }

      while (offset < file.size) {
        const t0 = performance.now();
        const chunk = file.slice(offset, offset + CHUNK);
        const buf = await chunk.arrayBuffer();
        let res = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            const resp = await fetch('/uploads/chunk/' + sessionId, {
              method: 'POST',
              headers: csrfHeaders({ 'Content-Type': 'application/octet-stream', 'X-Offset': String(offset) }),
              body: buf,
            });
            res = await resp.json();
            if (resp.ok) break;
          } catch (err) {
            if (attempt === 2) throw err;
          }
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
        }
        if (!res) {
          row.insertAdjacentHTML('beforeend', '<span class="upload-error">Ошибка загрузки</span>');
          return;
        }
        const dt = (performance.now() - t0) / 1000;
        const bytes = res.received - offset;
        offset = res.received;
        const p = Math.round((offset / file.size) * 100);
        fill.style.width = p + '%';
        pct.textContent = p + '%';
        if (dt > 0) speedEl.textContent = (bytes / dt / 1024 / 1024).toFixed(1) + ' MB/s';
      }

      const fin = await fetch('/uploads/finalize/' + sessionId, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({}),
      }).then(r => r.json());
      const id = fin.attachment_id || fin.file_id;
      if (id) ids.push(id);
      delete sessions[key];
      localStorage.setItem('uploadSessions', JSON.stringify(sessions));
      pct.textContent = '100%';
      speedEl.textContent = '';
      row.insertAdjacentHTML('beforeend', '<span class="upload-done">Готово</span>');
    }
  }

  window.initUploadZone = initUploadZone;
  initUploadZone({});
})();
