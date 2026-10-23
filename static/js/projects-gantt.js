(function () {

  var chart = document.querySelector("[data-gantt-chart]");

  if (!chart) return;



  var csrfEl = document.querySelector('meta[name="csrf-token"]');

  var csrf = csrfEl ? csrfEl.content : "";

  var flagsEl = document.getElementById("gantt-ui-flags");

  var uiFlags = { canEdit: false };

  try { if (flagsEl) uiFlags = JSON.parse(flagsEl.textContent || "{}"); } catch (e) {}

  var spanStart = chart.getAttribute("data-span-start");

  var spanEnd = chart.getAttribute("data-span-end");

  var ganttScale = chart.getAttribute("data-scale") || "month";

  var ganttCols = Math.max(1, parseInt(chart.getAttribute("data-cols") || "1", 10) || 1);
  var ganttScrollKey = "gantt-scroll:" + location.pathname + location.search;
  var ganttScrollKeyLegacy = "gantt-hscroll:" + location.pathname + location.search;

  function saveGanttScroll() {
    var h = chart.querySelector(".projects-gantt-hscroll");
    if (!h) return;
    try {
      sessionStorage.setItem(
        ganttScrollKey,
        JSON.stringify({
          left: Math.round(h.scrollLeft),
          top: Math.round(h.scrollTop),
        })
      );
    } catch (e) {}
  }

  function reloadGantt() {
    saveGanttScroll();
    window.location.reload();
  }

  function ganttAlert(message, title) {
    if (typeof window.ssAlert === "function") {
      return window.ssAlert(message, { title: title || "Внимание" });
    }
    window.alert(message);
    return Promise.resolve(true);
  }

  function parseIso(s) {

    if (!s) return null;

    var p = s.split("-");

    return new Date(+p[0], +p[1] - 1, +p[2]);

  }



  function isoDate(d) {

    var m = d.getMonth() + 1;

    var day = d.getDate();

    return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;

  }



  function daySpan() {

    var a = parseIso(spanStart);

    var b = parseIso(spanEnd);

    if (!a || !b) return 1;

    return Math.max(1, Math.round((b - a) / 86400000) + 1);

  }



  function daysInMonth(y, m0) {

    return new Date(y, m0 + 1, 0).getDate();

  }



  function sideWidth() {

    var side = chart.querySelector(".projects-gantt-side-head");

    return side ? side.offsetWidth : 320;

  }



  /** Квартал: доля месячных слотов → дата (как _bar_geometry на сервере). */
  function quarterFracToDate(frac, endOfDay) {

    var base = parseIso(spanStart);

    if (!base) return null;

    var slot = Math.floor(frac);

    var part = frac - slot;

    if (slot < 0) { slot = 0; part = 0; }

    if (slot >= ganttCols) { slot = ganttCols - 1; part = 1; }

    var d = new Date(base.getFullYear(), base.getMonth() + slot, 1);

    var dim = daysInMonth(d.getFullYear(), d.getMonth());

    var day = endOfDay

      ? Math.max(1, Math.min(dim, Math.round(part * dim)))

      : Math.max(1, Math.min(dim, Math.floor(part * dim) + 1));

    return new Date(d.getFullYear(), d.getMonth(), day);

  }



  function pctToDates(leftPct, widthPct) {

    var base = parseIso(spanStart);

    if (!base) return { start: spanStart, due: spanEnd };



    if (ganttScale === "quarter") {

      var startF = (leftPct / 100) * ganttCols;

      var endF = ((leftPct + widthPct) / 100) * ganttCols;

      var qs = quarterFracToDate(startF, false);

      var qe = quarterFracToDate(endF, true);

      if (!qs || !qe) return { start: spanStart, due: spanEnd };

      if (qe < qs) qe = new Date(qs.getTime());

      return { start: isoDate(qs), due: isoDate(qe) };

    }



    var days = daySpan();

    var startOff = Math.round((leftPct / 100) * days);

    var endOff = Math.round(((leftPct + widthPct) / 100) * days) - 1;

    if (endOff < startOff) endOff = startOff;

    var s = new Date(base.getTime());

    s.setDate(s.getDate() + startOff);

    var e = new Date(base.getTime());

    e.setDate(e.getDate() + endOff);

    return { start: isoDate(s), due: isoDate(e) };

  }



  function slaBreach(dueIso, projectDeadline) {

    return !!(dueIso && projectDeadline && dueIso > projectDeadline);

  }



  var body = chart.querySelector(".projects-gantt-body");

  function drawFsLinks() {

    var svg = chart.querySelector(".projects-gantt-fs-svg");

    var raw = document.getElementById("gantt-fs-links");

    if (!body || !svg || !raw) return;



    var links;

    try {

      links = JSON.parse(raw.textContent || "[]");

    } catch (e) {

      return;

    }



    svg.innerHTML = "";

    if (!links.length) return;



    var w = body.clientWidth;

    var h = body.clientHeight;

    if (w < 40 || h < 40) return;



    // SVG на всю ширину body; левая колонка выше по z-index и перекрывает линии
    svg.setAttribute("width", w);

    svg.setAttribute("height", h);

    svg.style.left = "0";

    svg.style.width = w + "px";

    svg.style.height = h + "px";



    // Синяя FS по жёлтому маршруту:
    // выход вправо → вниз → к левому краю → вдоль края вниз → вход влево
    svg.innerHTML =
      '<defs>' +
      '<marker id="gantt-fs-dot" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="5" refY="5">' +
      '<circle cx="5" cy="5" r="3" fill="#1e40af"/></marker>' +
      '<marker id="gantt-fs-dot-hover" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="5" refY="5">' +
      '<circle cx="5" cy="5" r="3" fill="#dc2626"/></marker>' +
      '<marker id="gantt-fs-arrow" markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" viewBox="0 0 7 7">' +
      '<path d="M0.5,0.7 L6,3.5 L0.5,6.3 Z" fill="#1e40af"/></marker>' +
      '<marker id="gantt-fs-arrow-hover" markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" viewBox="0 0 7 7">' +
      '<path d="M0.5,0.7 L6,3.5 L0.5,6.3 Z" fill="#dc2626"/></marker>' +
      '</defs>';

    var svgRect = svg.getBoundingClientRect();

    links.forEach(function (link) {
      var fromRow = chart.querySelector('.projects-gantt-row[data-task-id="' + link.from_id + '"]');
      var toRow = chart.querySelector('.projects-gantt-row[data-task-id="' + link.to_id + '"]');
      if (!fromRow || !toRow) return;
      if (fromRow.classList.contains("is-gantt-folded") || toRow.classList.contains("is-gantt-folded")) return;
      if (fromRow.hidden || toRow.hidden) return;
      var fromBar = fromRow.querySelector(".projects-gantt-bar");
      var toBar = toRow.querySelector(".projects-gantt-bar");
      if (!fromBar || !toBar) return;

      var fr = fromBar.getBoundingClientRect();
      var tr = toBar.getBoundingClientRect();

      var x1 = fr.right - svgRect.left;
      var barLeft = tr.left - svgRect.left;
      var gap = barLeft - x1;
      var x2 = barLeft + 3;
      // Дальше влево на перегибе — явный заход в левый край
      var bendLeft = barLeft - 28;
      var y1 = fr.top + fr.height / 2 - svgRect.top;
      var y2 = tr.top + tr.height / 2 - svgRect.top;

      if (!isFinite(x1) || !isFinite(x2) || !isFinite(y1) || !isFinite(y2)) return;
      if (y1 < -20 || y2 < -20 || y1 > h + 20 || y2 > h + 20) return;

      if (Math.abs(y1 - y2) < 2 && gap > 10) {
        appendPath(svg, "M" + x1 + "," + y1 + " L" + x2 + "," + y2, link);
        return;
      }

      var stub = 10;
      var vx = x1 + stub;
      var midY = y1 + (y2 - y1) * 0.55;
      if (Math.abs(y2 - y1) < 16) midY = y1 + (y2 - y1) * 0.5;

      // вправо → вниз → длиннее влево → вниз → вход в левый край
      var d =
        "M" + x1 + "," + y1 +
        " H" + vx +
        " V" + midY +
        " H" + bendLeft +
        " V" + y2 +
        " H" + x2;
      appendPath(svg, d, link);
    });

  }



  function appendPath(svg, d, link) {

    var visible = document.createElementNS("http://www.w3.org/2000/svg", "path");

    visible.setAttribute("d", d);

    visible.setAttribute("class", "projects-gantt-fs-path");
    visible.setAttribute("marker-start", "url(#gantt-fs-dot)");
    visible.setAttribute("marker-end", "url(#gantt-fs-arrow)");

    var tip = (link && link.label)
      ? ("FS: " + link.label)
      : "Связь FS (конец → начало)";
    if (link && link.id) {
      visible.setAttribute("data-link-id", String(link.id));
    }
    visible.setAttribute("title", tip);
    var titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
    titleEl.textContent = tip;
    visible.appendChild(titleEl);

    svg.appendChild(visible);

    if (!uiFlags.canEdit || !link || !link.id) return;

    var hit = document.createElementNS("http://www.w3.org/2000/svg", "path");

    hit.setAttribute("d", d);

    hit.setAttribute("class", "projects-gantt-fs-hit");

    hit.setAttribute("data-link-id", String(link.id));

    hit.setAttribute("role", "button");

    hit.setAttribute("tabindex", "0");

    hit.setAttribute("aria-label", tip + ". Клик — удалить");

    hit.setAttribute("title", tip + " · клик — удалить");
    var hitTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
    hitTitle.textContent = tip + " · клик — удалить";
    hit.appendChild(hitTitle);

    hit.addEventListener("mouseenter", function () {

      visible.classList.add("is-hover");

    });

    hit.addEventListener("mouseleave", function () {

      visible.classList.remove("is-hover");

    });

    hit.addEventListener("click", function (e) {

      e.preventDefault();

      e.stopPropagation();

      deleteGanttLink(link.id);

    });

    hit.addEventListener("keydown", function (e) {

      if (e.key === "Enter" || e.key === " ") {

        e.preventDefault();

        deleteGanttLink(link.id);

      }

    });

    svg.appendChild(hit);

  }



  var drag = null;
  var suppressBarClick = false;

  function collectDescendantSlots(rootTaskId) {
    var byParent = {};
    chart.querySelectorAll(".projects-gantt-row[data-task-id]").forEach(function (row) {
      var pid = row.getAttribute("data-parent-id") || "";
      if (!pid) return;
      if (!byParent[pid]) byParent[pid] = [];
      byParent[pid].push(row.getAttribute("data-task-id"));
    });
    var out = [];
    var queue = (byParent[String(rootTaskId)] || []).slice();
    var seen = {};
    while (queue.length) {
      var id = queue.shift();
      if (!id || seen[id]) continue;
      seen[id] = true;
      var row = chart.querySelector('.projects-gantt-row[data-task-id="' + id + '"]');
      if (row) {
        var slot = row.querySelector(".projects-gantt-bar-slot");
        if (slot) {
          out.push({
            id: id,
            slot: slot,
            origLeft: parseFloat(slot.style.left) || 0,
          });
        }
      }
      var kids = byParent[id] || [];
      for (var i = 0; i < kids.length; i++) queue.push(kids[i]);
    }
    return out;
  }

  function parentSlotBounds(taskId) {
    var row = chart.querySelector('.projects-gantt-row[data-task-id="' + taskId + '"]');
    if (!row) return null;
    var parentId = row.getAttribute("data-parent-id") || "";
    if (!parentId) return null;
    var parentRow = chart.querySelector('.projects-gantt-row[data-task-id="' + parentId + '"]');
    if (!parentRow) return null;
    var slot = parentRow.querySelector(".projects-gantt-bar-slot");
    if (!slot) return null;
    var left = parseFloat(slot.style.left) || 0;
    var width = parseFloat(slot.getAttribute("data-width-pct")) || 0;
    if (width <= 0) return null;
    return { left: left, width: width };
  }

  function onPointerMove(e) {
    if (!drag) return;
    var tr = drag.track.getBoundingClientRect();
    var dx = e.clientX - drag.startX;
    if (Math.abs(dx) > 4) drag.moved = true;
    var dPct = (dx / tr.width) * 100;
    var minLeft = 0;
    var maxLeft = 100 - drag.widthPct;
    if (drag.parentBounds) {
      minLeft = drag.parentBounds.left;
      maxLeft = drag.parentBounds.left + drag.parentBounds.width - drag.widthPct;
      if (maxLeft < minLeft) maxLeft = minLeft;
    }
    var newLeft = Math.max(minLeft, Math.min(maxLeft, drag.origLeft + dPct));
    drag.slot.style.left = newLeft + "%";
    var shift = newLeft - drag.origLeft;
    if (drag.children) {
      drag.children.forEach(function (ch) {
        ch.slot.style.left = (ch.origLeft + shift) + "%";
      });
    }
    var dates = pctToDates(newLeft, drag.widthPct);
    drag.bar.classList.toggle("is-critical-pulse", slaBreach(dates.due, drag.projectDeadline) || drag.wasCritical);
    scheduleDraw();
  }

  async function onPointerUp(e) {
    if (!drag) return;
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerup", onPointerUp);
    var state = drag;
    drag = null;
    state.bar.classList.remove("is-dragging");
    var dx = e && typeof e.clientX === "number" ? Math.abs(e.clientX - state.startX) : 0;
    var moved = state.moved || dx > 4;

    if (!moved) {
      state.slot.style.left = state.origLeft + "%";
      if (state.children) {
        state.children.forEach(function (ch) {
          ch.slot.style.left = ch.origLeft + "%";
        });
      }
      scheduleDraw();
      return;
    }

    suppressBarClick = true;
    setTimeout(function () { suppressBarClick = false; }, 0);

    var left = parseFloat(state.slot.style.left) || state.origLeft;
    var dates = pctToDates(left, state.widthPct);

    try {
      var res = await fetch("/projects/gantt/tasks/" + state.taskId + "/dates", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ start_date: dates.start, due_date: dates.due }),
      });
      if (res.ok) reloadGantt();
      else reloadGantt();
    } catch (err) {
      reloadGantt();
    }
  }



  var linkMode = false;
  var linkFromId = null; // предшествующая (уже выбрана)
  var linkToId = null; // задача «выполнить после…» (ждёт указания предшествующей)
  var nestMode = false;
  var nestChildId = null;
  var linkBtn = document.getElementById("gantt-link-mode-btn");
  var linkHint = document.getElementById("gantt-link-hint");
  var ctxMenu = document.getElementById("gantt-bar-menu");
  var ctxTaskId = null;

  function clearLinkSourceMarks() {
    chart.querySelectorAll(".projects-gantt-bar.is-link-source").forEach(function (el) {
      el.classList.remove("is-link-source");
    });
  }

  function barParentId(bar) {
    var row = bar && bar.closest ? bar.closest(".projects-gantt-row") : null;
    return row ? (row.getAttribute("data-parent-id") || "") : "";
  }

  function updateModeHint() {
    if (!linkHint) return;
    if (nestMode) {
      linkHint.hidden = false;
      linkHint.textContent = nestChildId
        ? "Выберите родителя для подзадачи (клик или ПКМ)"
        : "Режим вложения";
      return;
    }
    if (linkMode) {
      linkHint.hidden = false;
      if (linkToId) {
        linkHint.textContent = "Укажите предшествующую задачу (клик или ПКМ)";
      } else if (linkFromId) {
        linkHint.textContent = "Теперь выберите задачу, которая выполнится после неё";
      } else {
        linkHint.textContent = "Клик: задача → укажите предшествующую (или ПКМ «Выполнить после…»)";
      }
      return;
    }
    linkHint.hidden = true;
  }

  function setLinkMode(on, opts) {
    if (on) setNestMode(false);
    opts = opts || {};
    linkMode = !!on;
    linkFromId = on ? (opts.fromId || null) : null;
    linkToId = on ? (opts.toId || null) : null;
    if (linkBtn) linkBtn.classList.toggle("is-active", linkMode);
    chart.classList.toggle("is-link-mode", linkMode);
    clearLinkSourceMarks();
    var markId = linkToId || linkFromId;
    if (markId) {
      var src = chart.querySelector('.projects-gantt-bar[data-task-id="' + markId + '"]');
      if (src) src.classList.add("is-link-source");
    }
    updateModeHint();
  }

  function setNestMode(on, childId) {
    if (on) setLinkMode(false);
    nestMode = !!on;
    nestChildId = childId || null;
    chart.classList.toggle("is-nest-mode", nestMode);
    clearLinkSourceMarks();
    if (nestChildId) {
      var src = chart.querySelector('.projects-gantt-bar[data-task-id="' + nestChildId + '"]');
      if (src) src.classList.add("is-link-source");
    }
    updateModeHint();
  }

  function hideCtxMenu() {
    if (!ctxMenu) return;
    ctxMenu.hidden = true;
    ctxTaskId = null;
  }

  function showCtxMenu(bar, clientX, clientY) {
    if (!ctxMenu || !uiFlags.canEdit) return;
    ctxTaskId = bar.getAttribute("data-task-id");
    var subtaskLink = ctxMenu.querySelector('[data-gantt-ctx="subtask"]');
    var promoteBtn = ctxMenu.querySelector('[data-gantt-ctx="promote"]');
    var nestStartBtn = ctxMenu.querySelector('[data-gantt-ctx="nest-start"]');
    var nestFinishBtn = ctxMenu.querySelector('[data-gantt-ctx="nest-finish"]');
    var startBtn = ctxMenu.querySelector('[data-gantt-ctx="start-link"]');
    var clearPredBtn = ctxMenu.querySelector('[data-gantt-ctx="clear-predecessors"]');
    var finishBtn = ctxMenu.querySelector('[data-gantt-ctx="finish-link"]');
    var cancelBtn = ctxMenu.querySelector('[data-gantt-ctx="cancel-link"]');
    var canPickPredecessor = !!(
      linkMode && linkToId && String(linkToId) !== String(ctxTaskId)
    );
    var canPickSuccessor = !!(
      linkMode && linkFromId && !linkToId && String(linkFromId) !== String(ctxTaskId)
    );
    var canFinish = canPickPredecessor || canPickSuccessor;
    var canNestFinish = !!(nestMode && nestChildId && String(nestChildId) !== String(ctxTaskId));
    var waits = parseBarLinks(bar, "data-waits");
    var hasPredecessors = waits.some(function (w) { return w && w.link_id; });
    var hasParent = !!barParentId(bar);
    if (subtaskLink && ctxTaskId) {
      subtaskLink.href = "/projects/tasks/new?parent=" + encodeURIComponent(ctxTaskId) + "&arm_view=gantt";
      subtaskLink.hidden = !!nestMode || !!linkMode;
    }
    if (promoteBtn) promoteBtn.hidden = !hasParent || nestMode || linkMode;
    if (nestStartBtn) nestStartBtn.hidden = !!nestMode || !!linkMode;
    if (nestFinishBtn) nestFinishBtn.hidden = !canNestFinish;
    // «Выполнить после…» всегда доступно; если связь уже есть — ещё и «убрать»
    if (startBtn) startBtn.hidden = !!nestMode || !!linkMode;
    if (clearPredBtn) clearPredBtn.hidden = !hasPredecessors || nestMode || linkMode;
    if (finishBtn) {
      finishBtn.hidden = !canFinish;
      finishBtn.textContent = canPickPredecessor
        ? "Указать предшествующую задачу"
        : "Выполнить после этой задачи";
    }
    if (cancelBtn) cancelBtn.hidden = !(linkMode || nestMode);
    ctxMenu.hidden = false;
    var pad = 8;
    var w = ctxMenu.offsetWidth || 240;
    var h = ctxMenu.offsetHeight || 120;
    var left = Math.min(clientX, window.innerWidth - w - pad);
    var top = Math.min(clientY, window.innerHeight - h - pad);
    ctxMenu.style.left = Math.max(pad, left) + "px";
    ctxMenu.style.top = Math.max(pad, top) + "px";
  }

  if (linkBtn) {
    linkBtn.addEventListener("click", function () {
      if (linkMode) setLinkMode(false);
      else setLinkMode(true, {});
    });
  }

  async function changeTaskHierarchy(taskId, payload, _retried) {
    try {
      var body = Object.assign({}, payload || {});
      if (body.break_links) body.break_links = true;
      var res = await fetch("/projects/tasks/" + taskId + "/hierarchy", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
          "Accept": "application/json",
        },
        body: JSON.stringify(body),
      });
      var data = {};
      var ct = (res.headers.get("content-type") || "").toLowerCase();
      if (ct.indexOf("application/json") >= 0) {
        try { data = await res.json(); } catch (e) { data = {}; }
      } else {
        ganttAlert("Сессия устарела или ответ сервера неверный. Обновите страницу (Ctrl+F5).");
        return false;
      }
      var needsBreak = (res.status === 409 && data && data.error === "has_links")
        || (data && data.error === "has_links");
      if (needsBreak && !_retried) {
        var ask = (data && data.message) || "У задачи есть связи. Разорвать?";
        var ok = true;
        if (typeof window.ssConfirm === "function") {
          ok = await window.ssConfirm("", {
            title: ask,
            confirmLabel: "Разорвать",
            cancelLabel: "Отмена",
            danger: true,
          });
        } else {
          ok = window.confirm(ask);
        }
        if (!ok) return false;
        return changeTaskHierarchy(taskId, Object.assign({}, body, { break_links: true }), true);
      }
      if (!res.ok) {
        var msg = (data && data.message) || "";
        if (!msg || msg === "Не найдено.") {
          if (res.status === 404) msg = "Задача не найдена. Обновите Гант (Ctrl+F5) и повторите.";
          else if (res.status === 403) msg = "Недостаточно прав для смены вложенности (верхний уровень — только ГИП).";
          else if (res.status === 400) msg = "Нельзя так изменить вложенность (например, вложить задачу в свою подзадачу).";
          else msg = "Не удалось изменить вложенность.";
        }
        ganttAlert(msg);
        return false;
      }
      reloadGantt();
      return true;
    } catch (err) {
      ganttAlert("Ошибка сети.");
      return false;
    }
  }

  if (ctxMenu) {
    ctxMenu.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-gantt-ctx]");
      if (!btn || !ctxTaskId) return;
      var action = btn.getAttribute("data-gantt-ctx");
      if (action === "subtask") {
        // переход по href — не preventDefault
        hideCtxMenu();
        return;
      }
      e.preventDefault();
      var taskId = ctxTaskId;
      if (action === "promote") {
        hideCtxMenu();
        if (!taskId) {
          ganttAlert("Не выбрана задача.");
          return;
        }
        changeTaskHierarchy(taskId, { action: "promote", parent_id: null });
        return;
      }
      if (action === "nest-start") {
        setNestMode(true, taskId);
        hideCtxMenu();
        return;
      }
      if (action === "nest-finish" && nestChildId) {
        var parentId = taskId;
        var childId = nestChildId;
        hideCtxMenu();
        setNestMode(false);
        if (!parentId || !childId) {
          ganttAlert("Не выбраны задачи для вложения.");
          return;
        }
        changeTaskHierarchy(childId, { action: "attach", parent_id: parseInt(parentId, 10) });
        return;
      }
      if (action === "start-link") {
        // Эта задача выполнится после выбранной следующей (предшествующей)
        setLinkMode(true, { toId: taskId });
        hideCtxMenu();
        return;
      }
      if (action === "clear-predecessors") {
        var bar = chart.querySelector('.projects-gantt-bar[data-task-id="' + taskId + '"]');
        var waits = bar ? parseBarLinks(bar, "data-waits") : [];
        var ids = waits.map(function (w) { return w && w.link_id; }).filter(Boolean);
        hideCtxMenu();
        clearPredecessorLinks(ids);
        return;
      }
      if (action === "finish-link") {
        if (linkToId && String(linkToId) !== String(taskId)) {
          createGanttLink(taskId, linkToId);
          hideCtxMenu();
          return;
        }
        if (linkFromId && String(linkFromId) !== String(taskId)) {
          createGanttLink(linkFromId, taskId);
          hideCtxMenu();
          return;
        }
      }
      if (action === "cancel-link") {
        setLinkMode(false);
        setNestMode(false);
        hideCtxMenu();
      }
    });
  }

  async function clearPredecessorLinks(linkIds) {
    if (!linkIds || !linkIds.length) return;
    var ok = true;
    if (typeof window.ssConfirm === "function") {
      ok = await window.ssConfirm(
        linkIds.length > 1
          ? "Убрать все связи «выполнить после» у этой задачи?"
          : "Убрать связь «выполнить после» у этой задачи?",
        {
          title: "Убрать «выполнить после»",
          confirmLabel: "Убрать",
          danger: true,
        }
      );
    }
    if (!ok) return;
    try {
      for (var i = 0; i < linkIds.length; i++) {
        var res = await fetch("/projects/gantt/links/" + linkIds[i], {
          method: "DELETE",
          headers: { "X-CSRFToken": csrf },
        });
        if (!res.ok) {
          ganttAlert("Не удалось удалить связь.");
          return;
        }
      }
      reloadGantt();
    } catch (err) {
      ganttAlert("Ошибка сети.");
    }
  }

  document.addEventListener("click", function (e) {
    if (!ctxMenu || ctxMenu.hidden) return;
    if (ctxMenu.contains(e.target)) return;
    hideCtxMenu();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      hideCtxMenu();
      if (linkMode) setLinkMode(false);
      if (nestMode) setNestMode(false);
    }
  });

  var panel = document.getElementById("gantt-task-panel");
  var panelTitle = document.getElementById("gantt-panel-title");
  var panelStart = document.getElementById("gantt-panel-start");
  var panelDue = document.getElementById("gantt-panel-due");
  var panelStage = document.getElementById("gantt-panel-stage");
  var panelStatus = document.getElementById("gantt-panel-status");
  var panelSave = document.getElementById("gantt-panel-save");
  var panelOpen = document.getElementById("gantt-panel-open");
  var panelNote = document.getElementById("gantt-panel-readonly-note");
  var panelClose = document.getElementById("gantt-panel-close");
  var panelLinksWrap = document.getElementById("gantt-panel-links-wrap");
  var panelLinks = document.getElementById("gantt-panel-links");
  var panelTaskId = null;

  async function deleteGanttLink(linkId) {
    if (!linkId) return;
    var ok = true;
    if (typeof window.ssConfirm === "function") {
      ok = await window.ssConfirm("Удалить эту связь?", {
        title: "Удаление связи",
        confirmLabel: "Удалить",
        danger: true,
      });
    }
    if (!ok) return;
    try {
      var res = await fetch("/projects/gantt/links/" + linkId, {
        method: "DELETE",
        headers: { "X-CSRFToken": csrf },
      });
      if (res.ok) reloadGantt();
      else ganttAlert("Не удалось удалить связь.");
    } catch (err) {
      ganttAlert("Ошибка сети.");
    }
  }

  function parseBarLinks(bar, attr) {
    try {
      return JSON.parse(bar.getAttribute(attr) || "[]") || [];
    } catch (e) {
      return [];
    }
  }

  function renderPanelLinks(bar, canEdit) {
    if (!panelLinks || !panelLinksWrap) return;
    var waits = parseBarLinks(bar, "data-waits");
    var blocks = parseBarLinks(bar, "data-blocks");
    panelLinks.innerHTML = "";
    function addItem(role, item) {
      if (!item || !item.link_id) return;
      var li = document.createElement("li");
      var text = document.createElement("span");
      var roleEl = document.createElement("span");
      roleEl.className = "muted";
      roleEl.textContent = role;
      text.appendChild(roleEl);
      text.appendChild(document.createTextNode(item.title || ("№" + item.id)));
      li.appendChild(text);
      if (canEdit) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-outline btn-icon-xs";
        btn.title = "Удалить связь";
        btn.setAttribute("aria-label", "Удалить связь");
        btn.textContent = "×";
        btn.addEventListener("click", function () {
          deleteGanttLink(item.link_id);
        });
        li.appendChild(btn);
      }
      panelLinks.appendChild(li);
    }
    waits.forEach(function (w) { addItem("Предшественник", w); });
    blocks.forEach(function (b) { addItem("Последователь", b); });
    panelLinksWrap.hidden = panelLinks.children.length === 0;
  }

  function closePanel() {
    if (!panel) return;
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    panelTaskId = null;
  }

  function openPanel(bar) {
    if (!panel) return;
    panelTaskId = bar.getAttribute("data-task-id");
    var canEdit = bar.getAttribute("data-can-edit") === "1";
    var openTicket = bar.getAttribute("data-open-ticket") === "1";
    var ticketId = bar.getAttribute("data-ticket-id");
    if (panelTitle) panelTitle.textContent = bar.getAttribute("data-title") || "Задача";
    if (panelStart) {
      panelStart.value = bar.getAttribute("data-start") || "";
      panelStart.disabled = !canEdit;
      var winMin = bar.getAttribute("data-parent-start") || bar.getAttribute("data-project-start") || "";
      var winMax = bar.getAttribute("data-parent-due") || bar.getAttribute("data-project-deadline") || "";
      if (winMin) panelStart.min = winMin; else panelStart.removeAttribute("min");
      if (winMax) panelStart.max = winMax; else panelStart.removeAttribute("max");
    }
    if (panelDue) {
      panelDue.value = bar.getAttribute("data-due") || "";
      panelDue.disabled = !canEdit;
      var dueMin = bar.getAttribute("data-parent-start") || bar.getAttribute("data-project-start") || "";
      var dueMax = bar.getAttribute("data-parent-due") || bar.getAttribute("data-project-deadline") || "";
      if (dueMin) panelDue.min = dueMin; else panelDue.removeAttribute("min");
      if (dueMax) panelDue.max = dueMax; else panelDue.removeAttribute("max");
    }
    if (panelStage) {
      var pid = bar.getAttribute("data-project-id");
      var sid = bar.getAttribute("data-stage-id") || "";
      Array.prototype.forEach.call(panelStage.options, function (opt) {
        if (!opt.value) return;
        var op = opt.getAttribute("data-project-id");
        opt.hidden = !!(op && pid && String(op) !== String(pid));
      });
      panelStage.value = sid;
      panelStage.disabled = !canEdit;
    }
    if (panelStatus) {
      panelStatus.value = bar.getAttribute("data-status") || "todo";
      panelStatus.disabled = !canEdit;
    }
    if (panelSave) panelSave.hidden = !canEdit;
    if (panelNote) panelNote.hidden = canEdit;
    if (panelOpen) {
      if (openTicket && ticketId) panelOpen.href = "/tickets/" + ticketId;
      else panelOpen.href = "/projects/tasks/" + panelTaskId + "?arm_view=gantt";
    }
    renderPanelLinks(bar, canEdit);
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
  }

  if (panelClose) panelClose.addEventListener("click", closePanel);
  if (panelSave) {
    panelSave.addEventListener("click", async function () {
      if (!panelTaskId) return;
      try {
        var res = await fetch("/projects/gantt/tasks/" + panelTaskId + "/panel", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({
            start_date: panelStart ? panelStart.value : "",
            due_date: panelDue ? panelDue.value : "",
            stage_id: panelStage ? panelStage.value : "",
            kanban_status: panelStatus ? panelStatus.value : "",
          }),
        });
        var data = {};
        try { data = await res.json(); } catch (e) {}
        if (res.ok) {
          reloadGantt();
          return;
        }
        if (res.status === 409) {
          ganttAlert("Нельзя сменить статус: есть блокирующие связи.");
          return;
        }
        ganttAlert((data && data.message) || "Не удалось сохранить.");
      } catch (err) {
        ganttAlert("Ошибка сети.");
      }
    });
  }

  async function createGanttLink(fromId, toId) {
    try {
      var res = await fetch("/projects/gantt/links", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ from_task_id: fromId, to_task_id: toId, link_type: "blocks" }),
      });
      if (res.ok) {
        reloadGantt();
        return;
      }
      var data = {};
      try { data = await res.json(); } catch (e) {}
      ganttAlert((data && data.message) || "Не удалось создать связь.");
    } catch (err) {
      ganttAlert("Ошибка сети.");
    }
  }

  document.querySelectorAll("[data-gantt-link-delete]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      deleteGanttLink(btn.getAttribute("data-gantt-link-delete"));
    });
  });

  chart.querySelectorAll(".projects-gantt-bar").forEach(function (bar) {
    if (bar.getAttribute("data-can-drag") === "1") {
      bar.addEventListener("pointerdown", function (e) {
      if (linkMode || nestMode) return;
      if (bar.getAttribute("data-can-drag") !== "1") return;
        e.preventDefault();
        e.stopPropagation();
        var slot = bar.closest(".projects-gantt-bar-slot");
        var track = bar.closest("[data-gantt-track]");
        if (!slot || !track) return;
        var taskId = bar.getAttribute("data-task-id");
        drag = {
          bar: bar,
          slot: slot,
          track: track,
          taskId: taskId,
          startX: e.clientX,
          origLeft: parseFloat(slot.style.left) || 0,
          widthPct: parseFloat(slot.getAttribute("data-width-pct")) || 10,
          projectDeadline: bar.getAttribute("data-project-deadline") || "",
          wasCritical: bar.classList.contains("is-critical-pulse"),
          moved: false,
          children: collectDescendantSlots(taskId),
          parentBounds: parentSlotBounds(taskId),
        };
        bar.classList.add("is-dragging");
        bar.setPointerCapture(e.pointerId);
        document.addEventListener("pointermove", onPointerMove);
        document.addEventListener("pointerup", onPointerUp);
      });
    }

    bar.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      hideCtxMenu();
      if (suppressBarClick) {
        suppressBarClick = false;
        return;
      }
      var id = bar.getAttribute("data-task-id");
      if (!id) return;
      if (nestMode) {
        if (!nestChildId) {
          setNestMode(true, id);
          return;
        }
        if (String(nestChildId) === String(id)) return;
        var childId = nestChildId;
        setNestMode(false);
        changeTaskHierarchy(childId, { action: "attach", parent_id: parseInt(id, 10) });
        return;
      }
      if (linkMode) {
        if (linkToId) {
          if (String(linkToId) === String(id)) return;
          createGanttLink(id, linkToId);
          return;
        }
        if (!linkFromId) {
          setLinkMode(true, { toId: id });
          return;
        }
        if (String(linkFromId) === String(id)) return;
        createGanttLink(linkFromId, id);
        return;
      }
      // После текущего click — иначе document-listener может сразу закрыть панель
      setTimeout(function () { openPanel(bar); }, 0);
    });

    if (uiFlags.canEdit) {
      bar.addEventListener("contextmenu", function (e) {
        e.preventDefault();
        e.stopPropagation();
        showCtxMenu(bar, e.clientX, e.clientY);
      });
    }
  });

  // Клик вне панели — закрыть
  document.addEventListener("click", function (e) {
    if (!panel || panel.hidden) return;
    if (panel.contains(e.target)) return;
    if (e.target.closest && e.target.closest(".projects-gantt-bar")) return;
    closePanel();
  });

  function syncStageGuidePositions() {
    var body = chart.querySelector(".projects-gantt-body");
    if (!body) return;
    var bodyRect = body.getBoundingClientRect();
    var ticks = chart.querySelectorAll(".projects-gantt-milestone-tick");
    chart.querySelectorAll(".projects-gantt-stage-guide").forEach(function (guide) {
      var tick = null;
      var mid = guide.getAttribute("data-milestone-id");
      if (mid) {
        tick = chart.querySelector('.projects-gantt-milestone-tick[data-milestone-id="' + mid + '"]');
        if (!tick) {
          tick = chart.querySelector('.projects-gantt-milestone-tick[data-milestone-ids~="' + mid + '"]');
        }
      }
      if (!tick) {
        var idx = parseInt(guide.getAttribute("data-guide-idx") || "", 10);
        if (isFinite(idx) && ticks[idx]) tick = ticks[idx];
      }
      if (!tick) return;
      var anchor = tick.querySelector(".projects-gantt-milestone-dot") || tick;
      var ar = anchor.getBoundingClientRect();
      var cx = ar.left + ar.width / 2 - bodyRect.left;
      guide.style.left = Math.round(cx) + "px";
    });
  }

  /** Подписи этапов в один уровень: ширина ≤ зазор до соседа, без вертикального сдвига. */
  function fitMilestoneCaptions() {
    var lane = chart.querySelector(".projects-gantt-milestone-lane");
    if (!lane) return;
    var ticks = Array.prototype.slice.call(
      chart.querySelectorAll(".projects-gantt-milestone-tick")
    );
    if (!ticks.length) return;

    ticks.sort(function (a, b) {
      return (parseFloat(a.style.left) || 0) - (parseFloat(b.style.left) || 0);
    });

    var laneRect = lane.getBoundingClientRect();
    var centers = ticks.map(function (tick) {
      var leftPct = parseFloat(tick.style.left) || 0;
      return laneRect.left + (laneRect.width * leftPct) / 100;
    });

    var maxCap = 280;
    var minCap = 36;
    var gapPad = 12;

    ticks.forEach(function (tick, i) {
      var cap = tick.querySelector(".projects-gantt-milestone-cap");
      if (!cap) return;
      var full = tick.getAttribute("data-full-title") || "";
      if (full) cap.textContent = full;

      var gapL = i > 0 ? centers[i] - centers[i - 1] : Math.max(80, centers[i] - laneRect.left);
      var gapR =
        i < centers.length - 1
          ? centers[i + 1] - centers[i]
          : Math.max(80, laneRect.right - centers[i]);
      var room = Math.max(minCap, Math.min(maxCap, Math.min(gapL, gapR) - gapPad));

      tick.classList.remove("is-cap-offset");
      tick.style.width = room + "px";
      tick.style.maxWidth = room + "px";
      cap.style.width = room + "px";
      cap.style.maxWidth = room + "px";
    });

    lane.style.minHeight = "";
  }

  function scheduleDraw() {
    requestAnimationFrame(function () {
      drawFsLinks();
      syncStageGuidePositions();
      fitMilestoneCaptions();
    });
  }

  // Ручной порядок строк: перетаскивание слева
  (function setupRowReorder() {
    if (!uiFlags.canEdit) return;
    var rows = Array.prototype.slice.call(chart.querySelectorAll(".projects-gantt-row.is-reorderable"));
    if (rows.length < 2) return;
    var dragRow = null;

    function rowList() {
      return Array.prototype.slice.call(chart.querySelectorAll(".projects-gantt-row.is-reorderable"));
    }

    function renumber() {
      var rows = rowList();
      var counters = {};
      var wbsById = {};
      rows.forEach(function (row, i) {
        row.id = "gantt-row-" + (i + 1);
        var id = row.getAttribute("data-task-id") || "";
        var parentId = row.getAttribute("data-parent-id") || "";
        var parentWbs = parentId ? wbsById[parentId] : null;
        var key = parentWbs != null ? parentId : "";
        if (parentWbs == null) parentId = "";
        counters[key] = (counters[key] || 0) + 1;
        var wbs = parentWbs != null ? parentWbs + "." + counters[key] : String(counters[key]);
        wbsById[id] = wbs;
        row.setAttribute("data-wbs", wbs);
        var no = row.querySelector(".projects-gantt-row-no");
        if (no) {
          no.textContent = wbs;
          no.setAttribute("title", "WBS " + wbs);
        }
      });
      scheduleDraw();
    }

    async function persistOrder() {
      var ids = rowList().map(function (r) { return r.getAttribute("data-task-id"); }).filter(Boolean);
      try {
        var res = await fetch("/projects/gantt/reorder", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ task_ids: ids }),
        });
        if (!res.ok) reloadGantt();
        else {
          // После сохранения порядка перезагрузить, чтобы дерево/WBS совпали с сервером
          reloadGantt();
        }
      } catch (err) {
        reloadGantt();
      }
    }

    rows.forEach(function (row) {
      var handle = row.querySelector(".projects-gantt-drag-handle");
      if (!handle) return;
      handle.addEventListener("dragstart", function (e) {
        e.stopPropagation();
        dragRow = row;
        row.classList.add("is-row-dragging");
        try {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", row.getAttribute("data-task-id") || "");
        } catch (err) {}
      });
      handle.addEventListener("dragend", function () {
        row.classList.remove("is-row-dragging");
        chart.querySelectorAll(".projects-gantt-row.is-row-drag-over").forEach(function (r) {
          r.classList.remove("is-row-drag-over");
        });
        if (dragRow) {
          renumber();
          persistOrder();
        }
        dragRow = null;
      });
      row.addEventListener("dragover", function (e) {
        if (!dragRow || dragRow === row) return;
        e.preventDefault();
        row.classList.add("is-row-drag-over");
        var list = row.parentNode;
        var rect = row.getBoundingClientRect();
        var before = e.clientY < rect.top + rect.height / 2;
        if (before) list.insertBefore(dragRow, row);
        else list.insertBefore(dragRow, row.nextSibling);
      });
      row.addEventListener("dragleave", function () {
        row.classList.remove("is-row-drag-over");
      });
      row.addEventListener("drop", function (e) {
        e.preventDefault();
        row.classList.remove("is-row-drag-over");
      });
    });
  })();

  // Свернуть / развернуть подзадачи (− / +)
  (function initGanttFold() {
    var rows = Array.prototype.slice.call(chart.querySelectorAll(".projects-gantt-row[data-task-id]"));
    if (!rows.length) return;
    var byParent = {};
    rows.forEach(function (row) {
      var pid = row.getAttribute("data-parent-id") || "";
      if (!pid) return;
      if (!byParent[pid]) byParent[pid] = [];
      byParent[pid].push(row);
    });
    var foldKey = "gantt-fold:" + location.pathname + location.search;
    var collapsed = {};
    try {
      collapsed = JSON.parse(sessionStorage.getItem(foldKey) || "{}") || {};
    } catch (e) {
      collapsed = {};
    }

    function isFoldedAway(row) {
      var pid = row.getAttribute("data-parent-id") || "";
      var guard = 0;
      while (pid && guard < 40) {
        if (collapsed[pid]) return true;
        var prow = chart.querySelector('.projects-gantt-row[data-task-id="' + pid + '"]');
        pid = prow ? (prow.getAttribute("data-parent-id") || "") : "";
        guard += 1;
      }
      return false;
    }

    function applyFold() {
      rows.forEach(function (row) {
        var id = row.getAttribute("data-task-id");
        var kids = byParent[id];
        var isParent = !!(kids && kids.length);
        var isCollapsed = !!(isParent && collapsed[id]);
        row.classList.toggle("is-collapsed", isCollapsed);
        var hide = isFoldedAway(row);
        row.classList.toggle("is-gantt-folded", hide);
        row.hidden = hide;
        var btn = row.querySelector(".projects-gantt-fold");
        if (btn) {
          btn.textContent = isCollapsed ? "+" : "−";
          btn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
          btn.title = isCollapsed ? "Развернуть подзадачи" : "Свернуть подзадачи";
        }
      });
      try {
        sessionStorage.setItem(foldKey, JSON.stringify(collapsed));
      } catch (e) {}
      scheduleDraw();
    }

    rows.forEach(function (row) {
      var id = row.getAttribute("data-task-id");
      if (!byParent[id] || !byParent[id].length) return;
      var top = row.querySelector(".projects-gantt-side-top");
      if (!top || top.querySelector(".projects-gantt-fold")) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "projects-gantt-fold";
      btn.setAttribute("aria-label", "Свернуть или развернуть подзадачи");
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (collapsed[id]) delete collapsed[id];
        else collapsed[id] = 1;
        applyFold();
      });
      var no = row.querySelector(".projects-gantt-row-no");
      if (no) top.insertBefore(btn, no);
      else top.insertBefore(btn, top.firstChild);
    });
    applyFold();
  })();

  // Быстрое переименование в боковой колонке
  chart.querySelectorAll("[data-gantt-rename]").forEach(function (btn) {
    btn.addEventListener("click", async function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (!uiFlags.canEdit) return;
      var tid = btn.getAttribute("data-gantt-rename");
      if (!tid) return;
      var side = btn.closest(".projects-gantt-side");
      var label = side ? side.querySelector("[data-gantt-title]") : null;
      var current = label ? (label.textContent || "").trim() : "";
      var next = null;
      if (typeof window.ssPrompt === "function") {
        next = await window.ssPrompt("Название задачи", current, {
          title: "Переименовать задачу",
          confirmLabel: "Сохранить",
        });
      } else {
        next = window.prompt("Название задачи", current);
      }
      if (next == null) return;
      next = next.trim();
      if (!next || next === current) return;
      try {
        var res = await fetch("/projects/gantt/tasks/" + tid + "/panel", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
            Accept: "application/json",
          },
          body: JSON.stringify({ title: next }),
          credentials: "same-origin",
        });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
          ganttAlert((data && data.error) || "Не удалось сохранить название");
          return;
        }
        var title = (data && data.title) || next;
        if (label) {
          label.textContent = title;
          label.setAttribute("title", title);
        }
        var bar = chart.querySelector('.projects-gantt-bar[data-task-id="' + tid + '"]');
        if (bar) bar.setAttribute("data-title", title);
      } catch (err) {
        ganttAlert("Ошибка сети");
      }
    });
  });

  scheduleDraw();
  var host = chart.querySelector(".projects-gantt-hscroll");
  if (host) {
    host.addEventListener("scroll", function () {
      scheduleDraw();
      saveGanttScroll();
    });
  }
  if (body && window.ResizeObserver) {
    new ResizeObserver(scheduleDraw).observe(body);
  }

  var colPx = Math.max(24, parseInt(chart.getAttribute("data-col-px") || "56", 10) || 56);
  var todayIso = chart.getAttribute("data-today") || "";

  function sideW() {
    var side = chart.querySelector(".projects-gantt-side-head");
    return side ? side.offsetWidth : 320;
  }

  function timelineW() {
    var head = chart.querySelector(".projects-gantt-cols-head");
    return head && head.offsetWidth ? head.offsetWidth : ganttCols * colPx;
  }

  function todayScrollLeft() {
    if (!host || !spanStart || !todayIso) return 0;
    var a = parseIso(spanStart);
    var t = parseIso(todayIso);
    if (!a || !t) return 0;
    var days = Math.max(0, Math.round((t - a) / 86400000));
    var frac;
    if (ganttScale === "quarter") {
      var slot = (t.getFullYear() - a.getFullYear()) * 12 + (t.getMonth() - a.getMonth());
      var dim = daysInMonth(t.getFullYear(), t.getMonth());
      frac = (slot + (t.getDate() - 1) / dim) / Math.max(1, ganttCols);
    } else {
      frac = days / Math.max(1, daySpan());
    }
    var timelineLeft = frac * timelineW();
    return Math.max(0, sideW() + timelineLeft - host.clientWidth * 0.35);
  }

  function scrollGanttTo(left, smooth) {
    if (!host) return;
    host.scrollTo({ left: left, top: host.scrollTop, behavior: smooth ? "smooth" : "auto" });
  }

  /** Центрирует полоску задачи в видимой области шкалы (с учётом текущего зума). */
  function centerTaskInView(taskId, smooth) {
    if (!host || !taskId) return false;
    var row = chart.querySelector('.projects-gantt-row[data-task-id="' + taskId + '"]');
    if (!row || row.hidden) return false;
    var slot = row.querySelector(".projects-gantt-bar-slot");
    if (!slot) return false;
    var hostRect = host.getBoundingClientRect();
    var rowRect = row.getBoundingClientRect();
    if (rowRect.top < hostRect.top + 4) {
      host.scrollTop += rowRect.top - hostRect.top - 4;
    } else if (rowRect.bottom > hostRect.bottom - 4) {
      host.scrollTop += rowRect.bottom - hostRect.bottom + 4;
    }
    hostRect = host.getBoundingClientRect();
    var slotRect = slot.getBoundingClientRect();
    var sw = sideW();
    var slotCenter = slotRect.left + slotRect.width / 2;
    var viewCenter = hostRect.left + sw + Math.max(40, hostRect.width - sw) / 2;
    scrollGanttTo(host.scrollLeft + (slotCenter - viewCenter), !!smooth);
    saveGanttScroll();
    row.classList.add("is-gantt-flash");
    window.setTimeout(function () { row.classList.remove("is-gantt-flash"); }, 900);
    scheduleDraw();
    return true;
  }

  chart.querySelectorAll("[data-gantt-focus]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      centerTaskInView(btn.getAttribute("data-gantt-focus"), true);
    });
  });

  chart.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#gantt-row-"]');
    if (!a) return;
    var id = (a.getAttribute("href") || "").replace(/^#/, "");
    if (!id) return;
    var targetRow = document.getElementById(id);
    if (!targetRow) return;
    e.preventDefault();
    var tid = targetRow.getAttribute("data-task-id");
    if (tid) centerTaskInView(tid, true);
    else {
      targetRow.scrollIntoView({ block: "nearest", behavior: "smooth" });
      targetRow.classList.add("is-gantt-flash");
      window.setTimeout(function () { targetRow.classList.remove("is-gantt-flash"); }, 900);
    }
  });


  function restoreGanttScroll() {
    if (!host) return false;
    try {
      var raw = sessionStorage.getItem(ganttScrollKey);
      if (raw == null || raw === "") {
        raw = sessionStorage.getItem(ganttScrollKeyLegacy);
      }
      if (raw == null || raw === "") return false;
      var left = 0;
      var top = 0;
      if (raw.charAt(0) === "{") {
        var st = JSON.parse(raw);
        left = parseInt(st.left, 10);
        top = parseInt(st.top, 10);
      } else {
        left = parseInt(raw, 10);
      }
      if (!isFinite(left)) return false;
      if (!isFinite(top)) top = 0;
      host.scrollLeft = left;
      host.scrollTop = top;
      return true;
    } catch (e) {
      return false;
    }
  }

  function scrollToProjectEdge(which) {
    if (!host) return;
    var maxLeft = Math.max(0, host.scrollWidth - host.clientWidth);
    scrollGanttTo(which === "end" ? maxLeft : 0, true);
    saveGanttScroll();
  }

  var panLeft = document.getElementById("gantt-pan-left");
  var panRight = document.getElementById("gantt-pan-right");
  var panToday = document.getElementById("gantt-pan-today");
  if (panLeft) panLeft.addEventListener("click", function () { scrollToProjectEdge("start"); });
  if (panRight) panRight.addEventListener("click", function () { scrollToProjectEdge("end"); });
  if (panToday) panToday.addEventListener("click", function () {
    scrollGanttTo(todayScrollLeft(), true);
    saveGanttScroll();
  });

  function initGanttScroll() {
    if (!restoreGanttScroll()) scrollGanttTo(todayScrollLeft(), false);
    scheduleDraw();
  }

  window.addEventListener("resize", scheduleDraw);

  // После reload — прежний скролл (X и Y); иначе «сегодня»
  requestAnimationFrame(function () {
    requestAnimationFrame(initGanttScroll);
  });
  window.addEventListener("load", function () {
    restoreGanttScroll();
    scheduleDraw();
  }, { once: true });
})();

