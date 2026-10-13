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
