(function () {
  const modal = document.getElementById('ss-confirm-modal');
  if (!modal) return;

  const msgEl = document.getElementById('ss-confirm-message');
  const titleEl = document.getElementById('ss-confirm-title');
  const okBtn = document.getElementById('ss-confirm-ok');
  const cancelBtn = document.getElementById('ss-confirm-cancel');
  let resolver = null;
  var alertMode = false;

  function setCancelVisible(visible) {
    cancelBtn.hidden = !visible;
    // .btn { display: inline-flex } перекрывает UA-стиль [hidden]
    cancelBtn.style.display = visible ? '' : 'none';
  }

  function close(result) {
    modal.classList.remove('open');
    document.body.classList.remove('modal-open');
    setCancelVisible(true);
    alertMode = false;
    const r = resolver;
    resolver = null;
    if (r) r(result);
  }

  function open(message, options) {
    const opts = options || {};
    alertMode = !!opts.alertOnly;
    titleEl.textContent = opts.title || (alertMode ? 'Сообщение' : 'Подтверждение');
    msgEl.textContent = message || '';
    okBtn.textContent = opts.confirmLabel || (alertMode ? 'OK' : 'Подтвердить');
    cancelBtn.textContent = opts.cancelLabel || 'Отмена';
    okBtn.className = opts.danger ? 'btn btn-outline btn-danger-text' : 'btn btn-primary';
    setCancelVisible(!alertMode);
    modal.classList.add('open');
    document.body.classList.add('modal-open');
    okBtn.focus();
    return new Promise(function (resolve) {
      resolver = resolve;
    });
  }

  function openAlert(message, options) {
    const opts = options || {};
    opts.alertOnly = true;
    if (!opts.title) opts.title = 'Внимание';
    if (!opts.confirmLabel) opts.confirmLabel = 'OK';
    return open(message, opts).then(function () { return true; });
  }

  okBtn.addEventListener('click', function () {
    close(true);
  });
  cancelBtn.addEventListener('click', function () {
    // В alert «Отмена» только закрывает окно (связь уже отклонена сервером)
    close(alertMode ? true : false);
  });
  modal.addEventListener('click', function (e) {
    if (e.target === modal) close(alertMode ? true : false);
  });
  document.addEventListener('keydown', function (e) {
    if (!modal.classList.contains('open')) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      close(alertMode ? true : false);
    }
    if (alertMode && e.key === 'Enter') {
      e.preventDefault();
      close(true);
    }
  });

  window.ssConfirm = open;
  window.ssAlert = openAlert;

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
