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



    svg.innerHTML =

      '<defs><marker id="gantt-fs-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">' +

      '<path d="M0,0 L7,3.5 L0,7 Z" fill="#1e40af"/></marker></defs>';



    var svgRect = svg.getBoundingClientRect();



    links.forEach(function (link) {

      var fromRow = chart.querySelector('.projects-gantt-row[data-task-id="' + link.from_id + '"]');

      var toRow = chart.querySelector('.projects-gantt-row[data-task-id="' + link.to_id + '"]');

      if (!fromRow || !toRow) return;

      var fromBar = fromRow.querySelector(".projects-gantt-bar");

      var toBar = toRow.querySelector(".projects-gantt-bar");

      if (!fromBar || !toBar) return;



      var fr = fromBar.getBoundingClientRect();

      var tr = toBar.getBoundingClientRect();



      var x1 = fr.right - svgRect.left;

      var x2 = tr.left - svgRect.left;

      var y1 = fr.top + fr.height / 2 - svgRect.top;

      var y2 = tr.top + tr.height / 2 - svgRect.top;



      if (!isFinite(x1) || !isFinite(x2) || !isFinite(y1) || !isFinite(y2)) return;

      if (y1 < -20 || y2 < -20 || y1 > h + 20 || y2 > h + 20) return;



      if (Math.abs(y1 - y2) < 2 && x2 > x1) {

        appendPath(svg, "M" + x1 + "," + y1 + " L" + x2 + "," + y2, link);

        return;

      }



      var gutter = Math.min(Math.max(x1 + 12, x2 - 8), x1 + 40);

      if (gutter <= x1 + 2) gutter = x1 + 8;



      appendPath(svg, "M" + x1 + "," + y1 + " H" + gutter + " V" + y2 + " H" + x2, link);

    });

  }



  function appendPath(svg, d, link) {

    var visible = document.createElementNS("http://www.w3.org/2000/svg", "path");

    visible.setAttribute("d", d);

    visible.setAttribute("class", "projects-gantt-fs-path");

    visible.setAttribute("marker-end", "url(#gantt-fs-arrow)");

    if (link && link.id) {

      visible.setAttribute("data-link-id", String(link.id));

    }

    svg.appendChild(visible);



    if (!uiFlags.canEdit || !link || !link.id) return;



    var hit = document.createElementNS("http://www.w3.org/2000/svg", "path");

    hit.setAttribute("d", d);

    hit.setAttribute("class", "projects-gantt-fs-hit");

    hit.setAttribute("data-link-id", String(link.id));

    hit.setAttribute("role", "button");

    hit.setAttribute("tabindex", "0");

    hit.setAttribute("aria-label", "Удалить связь FS");

    hit.setAttribute("title", "Удалить связь");

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



  function onPointerMove(e) {

    if (!drag) return;

    var tr = drag.track.getBoundingClientRect();

    var dx = e.clientX - drag.startX;

    if (Math.abs(dx) > 4) drag.moved = true;

    var dPct = (dx / tr.width) * 100;

    var newLeft = Math.max(0, Math.min(100 - drag.widthPct, drag.origLeft + dPct));

    drag.slot.style.left = newLeft + "%";

    var dates = pctToDates(newLeft, drag.widthPct);

    drag.bar.classList.toggle("is-critical-pulse", slaBreach(dates.due, drag.projectDeadline) || drag.wasCritical);

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
      // Обычный клик: вернуть полоску, панель откроет обработчик click
      state.slot.style.left = state.origLeft + "%";
      return;
    }

    // После drag не открывать панель на синтетическом click
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

      if (res.ok) window.location.reload();

    } catch (err) {

      window.location.reload();

    }

  }



  var linkMode = false;
  var linkFromId = null;
  var linkBtn = document.getElementById("gantt-link-mode-btn");
  var linkHint = document.getElementById("gantt-link-hint");
  var ctxMenu = document.getElementById("gantt-bar-menu");
  var ctxTaskId = null;

  function clearLinkSourceMarks() {
    chart.querySelectorAll(".projects-gantt-bar.is-link-source").forEach(function (el) {
      el.classList.remove("is-link-source");
    });
  }

  function setLinkMode(on, fromId) {
    linkMode = !!on;
    linkFromId = fromId || null;
    if (linkBtn) linkBtn.classList.toggle("is-active", linkMode);
    if (linkHint) {
      linkHint.hidden = !linkMode;
      linkHint.textContent = linkFromId
        ? "Теперь выберите последователя (клик или ПКМ)"
        : "Выберите предшественника, затем последователя";
    }
    chart.classList.toggle("is-link-mode", linkMode);
    clearLinkSourceMarks();
    if (linkFromId) {
      var src = chart.querySelector('.projects-gantt-bar[data-task-id="' + linkFromId + '"]');
      if (src) src.classList.add("is-link-source");
    }
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
    var startBtn = ctxMenu.querySelector('[data-gantt-ctx="start-link"]');
    var finishBtn = ctxMenu.querySelector('[data-gantt-ctx="finish-link"]');
    var cancelBtn = ctxMenu.querySelector('[data-gantt-ctx="cancel-link"]');
    var canFinish = !!(linkMode && linkFromId && String(linkFromId) !== String(ctxTaskId));
    if (subtaskLink && ctxTaskId) {
      subtaskLink.href = "/projects/tasks/new?parent=" + encodeURIComponent(ctxTaskId);
      subtaskLink.hidden = false;
    }
    if (startBtn) startBtn.hidden = false;
    if (finishBtn) finishBtn.hidden = !canFinish;
    if (cancelBtn) cancelBtn.hidden = !linkMode;
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
      else setLinkMode(true);
    });
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
      if (action === "start-link") {
        setLinkMode(true, ctxTaskId);
        hideCtxMenu();
        return;
      }
      if (action === "finish-link" && linkFromId) {
        createGanttLink(linkFromId, ctxTaskId);
        hideCtxMenu();
        return;
      }
      if (action === "cancel-link") {
        setLinkMode(false);
        hideCtxMenu();
      }
    });
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
      if (res.ok) window.location.reload();
      else alert("Не удалось удалить связь.");
    } catch (err) {
      alert("Ошибка сети.");
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
    }
    if (panelDue) {
      panelDue.value = bar.getAttribute("data-due") || "";
      panelDue.disabled = !canEdit;
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
      else panelOpen.href = "/projects/tasks/" + panelTaskId;
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
        if (res.ok) window.location.reload();
        else if (res.status === 409) alert("Нельзя сменить статус: есть блокирующие связи.");
        else alert("Не удалось сохранить.");
      } catch (err) {
        alert("Ошибка сети.");
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
      if (res.ok) window.location.reload();
      else alert("Не удалось создать связь.");
    } catch (err) {
      alert("Ошибка сети.");
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
        if (linkMode) return;
        if (bar.getAttribute("data-can-drag") !== "1") return;
        e.preventDefault();
        e.stopPropagation();
        var slot = bar.closest(".projects-gantt-bar-slot");
        var track = bar.closest("[data-gantt-track]");
        if (!slot || !track) return;
        drag = {
          bar: bar,
          slot: slot,
          track: track,
          taskId: bar.getAttribute("data-task-id"),
          startX: e.clientX,
          origLeft: parseFloat(slot.style.left) || 0,
          widthPct: parseFloat(slot.getAttribute("data-width-pct")) || 10,
          projectDeadline: bar.getAttribute("data-project-deadline") || "",
          wasCritical: bar.classList.contains("is-critical-pulse"),
          moved: false,
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
      if (linkMode) {
        if (!linkFromId) {
          setLinkMode(true, id);
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

  function scheduleDraw() {
    requestAnimationFrame(drawFsLinks);
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
      rowList().forEach(function (row, i) {
        row.id = "gantt-row-" + (i + 1);
        var no = row.querySelector(".projects-gantt-row-no");
        if (no) no.textContent = String(i + 1);
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
        if (!res.ok) window.location.reload();
      } catch (err) {
        window.location.reload();
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

  scheduleDraw();
  window.addEventListener("resize", scheduleDraw);
  window.addEventListener("load", scheduleDraw);
  var host = chart.querySelector(".projects-gantt-hscroll");
  if (host) host.addEventListener("scroll", scheduleDraw);
  if (body && window.ResizeObserver) {
    new ResizeObserver(scheduleDraw).observe(body);
  }

  var colPx = Math.max(24, parseInt(chart.getAttribute("data-col-px") || "56", 10) || 56);
  var todayIso = chart.getAttribute("data-today") || "";

  function sideW() {
    var side = chart.querySelector(".projects-gantt-side-head");
    return side ? side.offsetWidth : 320;
  }

  function todayScrollLeft() {
    if (!host || !spanStart || !todayIso) return 0;
    var a = parseIso(spanStart);
    var t = parseIso(todayIso);
    if (!a || !t) return 0;
    var days = Math.max(0, Math.round((t - a) / 86400000));
    var frac;
    if (ganttScale === "quarter") {
      frac = (t.getFullYear() - a.getFullYear()) * 12 + (t.getMonth() - a.getMonth()) + (t.getDate() - 1) / 31;
      frac = frac / Math.max(1, ganttCols);
    } else {
      frac = days / Math.max(1, daySpan());
    }
    var timelineLeft = frac * (ganttCols * colPx);
    return Math.max(0, sideW() + timelineLeft - host.clientWidth * 0.35);
  }

  function scrollGanttTo(left, smooth) {
    if (!host) return;
    host.scrollTo({ left: left, behavior: smooth ? "smooth" : "auto" });
  }

  function panByCols(n) {
    if (!host) return;
    scrollGanttTo(host.scrollLeft + n * colPx * (ganttScale === "quarter" ? 1 : 3), true);
  }

  var panLeft = document.getElementById("gantt-pan-left");
  var panRight = document.getElementById("gantt-pan-right");
  var panToday = document.getElementById("gantt-pan-today");
  if (panLeft) panLeft.addEventListener("click", function () { panByCols(-1); });
  if (panRight) panRight.addEventListener("click", function () { panByCols(1); });
  if (panToday) panToday.addEventListener("click", function () {
    scrollGanttTo(todayScrollLeft(), true);
  });

  // Стартовая позиция — «сегодня» в видимой области (после раскладки)
  requestAnimationFrame(function () {
    scrollGanttTo(todayScrollLeft(), false);
    scheduleDraw();
  });
})();

