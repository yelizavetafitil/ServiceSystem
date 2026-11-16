(function () {
  var root = document.getElementById("ss-notify-root");
  if (!root) return;

  var feedUrl = root.getAttribute("data-feed-url");
  var ackUrl = root.getAttribute("data-ack-url");
  var readUrl = root.getAttribute("data-read-url");
  var deleteUrl = root.getAttribute("data-delete-url");
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

  function absUrl(url) {
    if (!url) return "";
    try {
      return new URL(url, window.location.origin).href;
    } catch (err) {
      return url;
    }
  }

  function ackToasts(ids) {
    if (!ids || !ids.length) return;
    postJson(ackUrl, { ids: ids }).catch(function () {});
  }

  function refreshListsOnly(data) {
    if (!data) return;
    var unread = data.unread || {};
    setBadge(document.getElementById("ss-notify-badge-ticket"), unread.ticket || 0);
    setBadge(document.getElementById("ss-notify-badge-task"), unread.task || 0);
    renderList(document.getElementById("ss-notify-list-ticket"), (data.recent || {}).ticket || []);
    renderList(document.getElementById("ss-notify-list-task"), (data.recent || {}).task || []);
  }

  function fetchFeed(withToasts) {
    return fetch(feedUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        refreshListsOnly(data);
        if (withToasts) {
          (data.toasts || []).forEach(function (n) {
            showToast(n);
          });
        }
      })
      .catch(function () {});
  }

  function removeToastById(id) {
    if (!toastBox) return;
    var el = toastBox.querySelector('.ss-toast[data-notify-id="' + id + '"]');
    if (el) el.remove();
    delete seenToast[id];
  }

  function deleteNotifications(payload) {
    return postJson(deleteUrl, payload).then(function (r) {
      return r.ok ? r.json() : null;
    });
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
        var href = absUrl(n.link_url || "#");
        var body = n.body ? '<span class="ss-notify-item-body">' + escapeHtml(n.body) + "</span>" : "";
        return (
          '<li class="' +
          cls +
          '" data-id="' +
          n.id +
          '"><a href="' +
          escapeAttr(href) +
          '"><strong>' +
          escapeHtml(n.title) +
          "</strong>" +
          body +
          '</a><button type="button" class="ss-notify-item-del" title="Удалить" aria-label="Удалить">&times;</button></li>'
        );
      })
      .join("");

    // Нативные ссылки — без preventDefault, чтобы переход всегда срабатывал.
    listEl.querySelectorAll(".ss-notify-item-del").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var li = btn.closest(".ss-notify-item");
        var id = li && li.getAttribute("data-id");
        if (!id) return;
        deleteNotifications({ ids: [Number(id)] }).then(function () {
          removeToastById(Number(id));
          li.remove();
          if (!listEl.querySelector(".ss-notify-item")) {
            listEl.innerHTML = '<li class="ss-notify-empty">Нет уведомлений</li>';
          }
          fetchFeed(false);
        });
      });
    });
  }

  function showToast(n) {
    if (!toastBox || seenToast[n.id]) return;
    var href = absUrl(n.link_url || "");
    if (!href) return;
    seenToast[n.id] = true;
    var el = document.createElement("div");
    el.className =
      "ss-toast ss-toast--" +
      (n.category || "ticket") +
      (n.is_urgent ? " is-urgent" : "");
    el.setAttribute("role", "status");
    el.dataset.notifyId = String(n.id);
    var kind = n.category === "task" ? "Задача" : "Заявка";
    el.innerHTML =
      '<div class="ss-toast-kind">' +
      kind +
      (n.is_urgent ? " · срочно" : "") +
      '</div><div class="ss-toast-title">' +
      escapeHtml(n.title) +
      "</div>" +
      (n.body ? '<div class="ss-toast-body">' + escapeHtml(n.body) + "</div>" : "") +
      '<div class="ss-toast-actions">' +
      '<a class="btn btn-sm btn-primary ss-toast-open" href="' +
      escapeAttr(href) +
      '">Открыть</a>' +
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
        // Не блокируем переход браузера — только ack и не даём клику закрыть панель.
        e.stopPropagation();
        ackToasts([n.id]);
      });
    }
    el.querySelector(".ss-toast-close").addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      close();
    });
    el.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  }

  function resetToastsFromCache() {
    seenToast = {};
    if (toastBox) toastBox.innerHTML = "";
    fetchFeed(true);
  }

  if (toastBox) {
    toastBox.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    toastBox.addEventListener(
      "wheel",
      function (e) {
        e.stopPropagation();
      },
      { passive: true }
    );
  }

  root.querySelectorAll(".ss-notify-list").forEach(function (list) {
    list.addEventListener(
      "wheel",
      function (e) {
        e.stopPropagation();
      },
      { passive: true }
    );
  });

  root.querySelectorAll("[data-notify-clear]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var cat = btn.getAttribute("data-notify-clear");
      if (!cat) return;
      deleteNotifications({ category: cat }).then(function () {
        Object.keys(seenToast).forEach(function (id) {
          removeToastById(Number(id));
        });
        fetchFeed(false);
      });
    });
  });

  function closeAllPanels() {
    root.querySelectorAll(".ss-notify-panel").forEach(function (p) {
      p.classList.remove("is-open");
    });
    root.querySelectorAll("[data-notify-toggle]").forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
    openPanel = null;
  }

  root.querySelectorAll("[data-notify-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var cat = btn.getAttribute("data-notify-toggle");
      var panel = document.getElementById("ss-notify-panel-" + cat);
      if (!panel) return;
      var willOpen = !panel.classList.contains("is-open");
      closeAllPanels();
      if (willOpen) {
        panel.classList.add("is-open");
        btn.setAttribute("aria-expanded", "true");
        openPanel = panel;
        postJson(readUrl, { category: cat }).then(function () {
          setBadge(document.getElementById("ss-notify-badge-" + cat), 0);
          fetchFeed(false);
        });
      }
    });
  });

  document.addEventListener("click", function (e) {
    if (!openPanel) return;
    if (root.contains(e.target)) return;
    if (toastBox && toastBox.contains(e.target)) return;
    closeAllPanels();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAllPanels();
  });

  // После «Назад» из bfcache тосты иначе не пересоздаются.
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) resetToastsFromCache();
  });

  fetchFeed(true);
  setInterval(function () {
    fetchFeed(true);
  }, 20000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) fetchFeed(true);
  });
})();
