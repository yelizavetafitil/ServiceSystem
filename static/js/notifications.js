(function () {
  var root = document.getElementById("ss-notify-root");
  if (!root) return;

  var feedUrl = root.getAttribute("data-feed-url");
  var ackUrl = root.getAttribute("data-ack-url");
  var readUrl = root.getAttribute("data-read-url");
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  var toastBox = document.getElementById("ss-toast-stack");
  var openPanel = null;
  var seenToast = {};

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify(payload || {}),
    });
  }

  function setBadge(el, n) {
    if (!el) return;
    if (n > 0) {
      el.hidden = false;
      el.textContent = n > 99 ? "99+" : String(n);
    } else {
      el.hidden = true;
      el.textContent = "";
    }
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function goTo(url) {
    if (!url) return;
    window.location.assign(url);
  }

  function ackToasts(ids) {
    if (!ids || !ids.length) return;
    postJson(ackUrl, { ids: ids }).catch(function () {});
  }

  function renderList(listEl, items) {
    if (!listEl) return;
    if (!items || !items.length) {
      listEl.innerHTML = '<li class="ss-notify-empty">Нет уведомлений</li>';
      return;
    }
    listEl.innerHTML = items
      .map(function (n) {
        var cls = "ss-notify-item" + (n.is_read ? "" : " is-unread") + (n.is_urgent ? " is-urgent" : "");
        var href = n.link_url || "#";
        var body = n.body ? '<span class="ss-notify-item-body">' + escapeHtml(n.body) + "</span>" : "";
        return (
          '<li class="' +
          cls +
          '"><a href="' +
          escapeAttr(href) +
          '"><strong>' +
          escapeHtml(n.title) +
          "</strong>" +
          body +
          "</a></li>"
        );
      })
      .join("");
    listEl.querySelectorAll(".ss-notify-item > a").forEach(function (a) {
      a.addEventListener("click", function (e) {
        var url = a.getAttribute("href");
        if (!url || url === "#") return;
        e.preventDefault();
        goTo(url);
      });
    });
  }

  function showToast(n) {
    if (!toastBox || seenToast[n.id]) return;
    seenToast[n.id] = true;
    var el = document.createElement("div");
    el.className =
      "ss-toast ss-toast--" +
      (n.category || "ticket") +
      (n.is_urgent ? " is-urgent" : "");
    el.setAttribute("role", "status");
    el.dataset.notifyId = String(n.id);
    var kind = n.category === "task" ? "Задача" : "Заявка";
    var href = n.link_url || "";
    el.innerHTML =
      '<div class="ss-toast-kind">' +
      kind +
      (n.is_urgent ? " · срочно" : "") +
      '</div><div class="ss-toast-title">' +
      escapeHtml(n.title) +
      "</div>" +
      (n.body ? '<div class="ss-toast-body">' + escapeHtml(n.body) + "</div>" : "") +
      '<div class="ss-toast-actions">' +
      (href
        ? '<a class="btn btn-sm btn-primary ss-toast-open" href="' + escapeAttr(href) + '">Открыть</a>'
        : "") +
      '<button type="button" class="btn btn-sm btn-outline ss-toast-close">Закрыть</button></div>';
    toastBox.appendChild(el);
    toastBox.scrollTop = toastBox.scrollHeight;

    var closed = false;
    var close = function () {
      if (closed) return;
      closed = true;
      ackToasts([n.id]);
      el.classList.add("is-hiding");
      setTimeout(function () {
        el.remove();
      }, 220);
    };

    var openBtn = el.querySelector(".ss-toast-open");
    if (openBtn) {
      openBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        ackToasts([n.id]);
        goTo(href);
      });
    }
    el.querySelector(".ss-toast-close").addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      close();
    });
    // Клик/скролл по карточке не должен ничего схлопывать.
    el.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  }

  function applyFeed(data) {
    if (!data) return;
    var unread = data.unread || {};
    setBadge(document.getElementById("ss-notify-badge-ticket"), unread.ticket || 0);
    setBadge(document.getElementById("ss-notify-badge-task"), unread.task || 0);
    renderList(document.getElementById("ss-notify-list-ticket"), (data.recent || {}).ticket || []);
    renderList(document.getElementById("ss-notify-list-task"), (data.recent || {}).task || []);

    (data.toasts || []).forEach(function (n) {
      showToast(n);
    });
  }

  function poll() {
    fetch(feedUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(applyFeed)
      .catch(function () {});
  }

  if (toastBox) {
    toastBox.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    toastBox.addEventListener("wheel", function (e) {
      e.stopPropagation();
    }, { passive: true });
  }

  root.querySelectorAll("[data-notify-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var cat = btn.getAttribute("data-notify-toggle");
      var panel = document.getElementById("ss-notify-panel-" + cat);
      if (!panel) return;
      var willOpen = openPanel !== panel;
      root.querySelectorAll(".ss-notify-panel").forEach(function (p) {
        p.hidden = true;
      });
      root.querySelectorAll("[data-notify-toggle]").forEach(function (b) {
        b.setAttribute("aria-expanded", "false");
      });
      if (willOpen) {
        panel.hidden = false;
        btn.setAttribute("aria-expanded", "true");
        openPanel = panel;
        postJson(readUrl, { category: cat }).then(function () {
          setBadge(document.getElementById("ss-notify-badge-" + cat), 0);
          // Обновляем только счётчики/список, без повторного схлопывания тостов.
          fetch(feedUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) {
              return r.ok ? r.json() : null;
            })
            .then(function (data) {
              if (!data) return;
              var unread = data.unread || {};
              setBadge(document.getElementById("ss-notify-badge-ticket"), unread.ticket || 0);
              setBadge(document.getElementById("ss-notify-badge-task"), unread.task || 0);
              renderList(document.getElementById("ss-notify-list-ticket"), (data.recent || {}).ticket || []);
              renderList(document.getElementById("ss-notify-list-task"), (data.recent || {}).task || []);
            })
            .catch(function () {});
        });
      } else {
        openPanel = null;
      }
    });
  });

  document.addEventListener("click", function (e) {
    if (!openPanel) return;
    if (root.contains(e.target)) return;
    if (toastBox && toastBox.contains(e.target)) return;
    root.querySelectorAll(".ss-notify-panel").forEach(function (p) {
      p.hidden = true;
    });
    root.querySelectorAll("[data-notify-toggle]").forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
    openPanel = null;
  });

  poll();
  setInterval(poll, 20000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
})();
