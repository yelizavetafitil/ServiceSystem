(function () {
  var root = document.getElementById('tutorial-structure');
  var ajaxRoot = document.getElementById('tutorial-structure-ajax-root');
  if (!root || !ajaxRoot) return;

  function csrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.content || '';
  }

  function showToast(message, ok) {
    var hint = document.getElementById('tutorial-structure-save-hint');
    if (hint) {
      hint.hidden = false;
      hint.textContent = message;
      hint.className = 'hint tutorial-structure-save-hint ' + (ok ? 'is-ok' : 'is-warn');
      window.setTimeout(function () {
        hint.hidden = true;
      }, 4000);
    } else if (window.ssAlert) {
      window.ssAlert(message, { title: ok ? 'Готово' : 'Внимание' });
    }
  }

  function replaceStructure(html) {
    ajaxRoot.innerHTML = html;
  }

  function structureSaveFormData(form) {
    var fd = new FormData(form);
    if (form.id !== 'tutorial-structure-save') return fd;
    var scope = ajaxRoot || root;
    scope.querySelectorAll('[form="tutorial-structure-save"]').forEach(function (el) {
      if (!el.name || el.disabled) return;
      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.checked) fd.set(el.name, el.value);
      } else {
        fd.set(el.name, el.value);
      }
    });
    return fd;
  }

  function submitStructureForm(form) {
    var btn = form.querySelector('button[type=submit]');
    if (btn) btn.disabled = true;
    var fd = structureSaveFormData(form);
    return fetch(form.action, {
      method: 'POST',
      body: fd,
      headers: {
        'X-Structure-Ajax': '1',
        'X-CSRFToken': csrfToken(),
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (btn) btn.disabled = false;
        if (!res.ok || !res.j) {
          showToast('Не удалось выполнить действие.', false);
          return;
        }
        if (res.j.html) replaceStructure(res.j.html);
        if (res.j.message) {
          showToast(res.j.message, res.j.ok !== false);
          var saveBar = document.querySelector('.tutorial-admin-save-bar');
          if (saveBar) {
            saveBar.scrollIntoView({ block: 'start', behavior: 'smooth' });
          } else {
            root.scrollIntoView({ block: 'start', behavior: 'smooth' });
          }
        }
        if (form.classList.contains('tutorial-admin-add-section')) {
          var inp = form.querySelector('input[name=section_title]');
          if (inp) inp.value = '';
        }
        if (form.classList.contains('tutorial-admin-add-lesson')) {
          var lin = form.querySelector('input[name=lesson_title]');
          if (lin) lin.value = '';
        }
      })
      .catch(function () {
        if (btn) btn.disabled = false;
        showToast('Ошибка сети.', false);
      });
  }

  root.addEventListener(
    'submit',
    function (e) {
      var form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (!form.hasAttribute('data-structure-ajax')) return;

      e.preventDefault();
      e.stopPropagation();
      submitStructureForm(form);
    },
    true
  );
})();
