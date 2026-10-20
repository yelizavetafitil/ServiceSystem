(function () {
  const modal = document.getElementById('ss-confirm-modal');
  if (!modal) return;

  const msgEl = document.getElementById('ss-confirm-message');
  const titleEl = document.getElementById('ss-confirm-title');
  const okBtn = document.getElementById('ss-confirm-ok');
  const cancelBtn = document.getElementById('ss-confirm-cancel');
  let resolver = null;

  function close(result) {
    modal.classList.remove('open');
    document.body.classList.remove('modal-open');
    const r = resolver;
    resolver = null;
    if (r) r(result);
  }

  function open(message, options) {
    const opts = options || {};
    titleEl.textContent = opts.title || 'Подтверждение';
    msgEl.textContent = message || '';
    okBtn.textContent = opts.confirmLabel || 'Подтвердить';
    cancelBtn.textContent = opts.cancelLabel || 'Отмена';
    okBtn.className = opts.danger ? 'btn btn-outline btn-danger-text' : 'btn btn-primary';
    modal.classList.add('open');
    document.body.classList.add('modal-open');
    okBtn.focus();
    return new Promise(function (resolve) {
      resolver = resolve;
    });
  }

  okBtn.addEventListener('click', function () {
    close(true);
  });
  cancelBtn.addEventListener('click', function () {
    close(false);
  });
  modal.addEventListener('click', function (e) {
    if (e.target === modal) close(false);
  });
  document.addEventListener('keydown', function (e) {
    if (!modal.classList.contains('open')) return;
    if (e.key === 'Escape') close(false);
  });

  window.ssConfirm = open;

  /* ---- ssPrompt: ввод текста в стиле сайта ---- */
  (function setupPrompt() {
    const pModal = document.getElementById('ss-prompt-modal');
    if (!pModal) return;
    const pTitle = document.getElementById('ss-prompt-title');
    const pLabel = document.getElementById('ss-prompt-label');
    const pInput = document.getElementById('ss-prompt-input');
    const pOk = document.getElementById('ss-prompt-ok');
    const pCancel = document.getElementById('ss-prompt-cancel');
    let pResolver = null;

    function pClose(value) {
      pModal.classList.remove('open');
      document.body.classList.remove('modal-open');
      const r = pResolver;
      pResolver = null;
      if (r) r(value);
    }

    function pOpen(label, defaultValue, options) {
      const opts = options || {};
      pTitle.textContent = opts.title || 'Ввод';
      pLabel.textContent = label || 'Значение';
      pInput.value = defaultValue == null ? '' : String(defaultValue);
      pOk.textContent = opts.confirmLabel || 'Сохранить';
      pCancel.textContent = opts.cancelLabel || 'Отмена';
      pModal.classList.add('open');
      document.body.classList.add('modal-open');
      requestAnimationFrame(function () {
        pInput.focus();
        pInput.select();
      });
      return new Promise(function (resolve) {
        pResolver = resolve;
      });
    }

    pOk.addEventListener('click', function () {
      pClose(pInput.value);
    });
    pCancel.addEventListener('click', function () {
      pClose(null);
    });
    pModal.addEventListener('click', function (e) {
      if (e.target === pModal) pClose(null);
    });
    pInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        pClose(pInput.value);
      }
    });
    document.addEventListener('keydown', function (e) {
      if (!pModal.classList.contains('open')) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        pClose(null);
      }
    });

    window.ssPrompt = pOpen;
  })();

  document.addEventListener(
    'submit',
    function (e) {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      const msg = form.getAttribute('data-confirm');
      if (!msg) return;
      if (form.dataset.confirmConfirmed === '1') {
        delete form.dataset.confirmConfirmed;
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      open(msg, {
        title: form.getAttribute('data-confirm-title') || undefined,
        confirmLabel: form.getAttribute('data-confirm-ok') || undefined,
        danger: form.hasAttribute('data-confirm-danger'),
      }).then(function (ok) {
        if (ok) {
          form.dataset.confirmConfirmed = '1';
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.submit();
          }
        }
      });
    },
    true
  );
})();
