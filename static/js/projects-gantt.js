(function () {

  var chart = document.querySelector("[data-gantt-chart]");

  if (!chart) return;



  var csrfEl = document.querySelector('meta[name="csrf-token"]');

  var csrf = csrfEl ? csrfEl.content : "";

  var spanStart = chart.getAttribute("data-span-start");

  var spanEnd = chart.getAttribute("data-span-end");



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



  function sideWidth() {

    var side = chart.querySelector(".projects-gantt-side-head");

    return side ? side.offsetWidth : 320;

  }



  function pctToDates(leftPct, widthPct) {

    var days = daySpan();

    var startOff = Math.round((leftPct / 100) * days);

    var endOff = Math.round(((leftPct + widthPct) / 100) * days) - 1;

    if (endOff < startOff) endOff = startOff;

    var base = parseIso(spanStart);

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



    var sideW = sideWidth();

    var w = Math.max(0, body.clientWidth - sideW);

    var h = body.clientHeight;

    if (w < 40 || h < 40) return;



    svg.setAttribute("width", w);

    svg.setAttribute("height", h);

    svg.style.left = sideW + "px";

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



      if (Math.abs(y1 - y2) < 2 && x2 > x1) {

        var d = "M" + x1 + "," + y1 + " L" + x2 + "," + y2;

        appendPath(svg, d);

        return;

      }



      var gutter = Math.min(Math.max(x1 + 12, x2 - 8), x1 + 40);

      if (gutter <= x1 + 2) gutter = x1 + 8;

      var d = "M" + x1 + "," + y1 + " H" + gutter + " V" + y2 + " H" + x2;

      appendPath(svg, d);

    });

  }



  function appendPath(svg, d) {

    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");

    path.setAttribute("d", d);

    path.setAttribute("class", "projects-gantt-fs-path");

    path.setAttribute("marker-end", "url(#gantt-fs-arrow)");

    svg.appendChild(path);

  }



  var drag = null;



  function onPointerMove(e) {

    if (!drag) return;

    var tr = drag.track.getBoundingClientRect();

    var dx = e.clientX - drag.startX;

    var dPct = (dx / tr.width) * 100;

    var newLeft = Math.max(0, Math.min(100 - drag.widthPct, drag.origLeft + dPct));

    drag.slot.style.left = newLeft + "%";

    var dates = pctToDates(newLeft, drag.widthPct);

    drag.bar.classList.toggle("is-critical-pulse", slaBreach(dates.due, drag.projectDeadline) || drag.wasCritical);

  }



  async function onPointerUp() {

    if (!drag) return;

    document.removeEventListener("pointermove", onPointerMove);

    document.removeEventListener("pointerup", onPointerUp);

    var state = drag;

    drag = null;

    state.bar.classList.remove("is-dragging");

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



  chart.querySelectorAll(".projects-gantt-bar.is-draggable").forEach(function (bar) {

    bar.addEventListener("pointerdown", function (e) {

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

      };

      bar.classList.add("is-dragging");

      bar.setPointerCapture(e.pointerId);

      document.addEventListener("pointermove", onPointerMove);

      document.addEventListener("pointerup", onPointerUp);

    });

    bar.addEventListener("dblclick", function () {

      var id = bar.getAttribute("data-task-id");

      if (id) window.location.href = "/projects/tasks/" + id;

    });

  });



  function scheduleDraw() {

    requestAnimationFrame(drawFsLinks);

  }



  scheduleDraw();

  window.addEventListener("resize", scheduleDraw);

  window.addEventListener("load", scheduleDraw);

  var host = chart.querySelector(".projects-gantt-hscroll");

  if (host) host.addEventListener("scroll", scheduleDraw);

  if (body && window.ResizeObserver) {
    new ResizeObserver(scheduleDraw).observe(body);
  }

})();

