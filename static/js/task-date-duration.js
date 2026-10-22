(function (global) {
  var HOLIDAY_MD = {
    "01-01": 1, "01-02": 1, "01-07": 1, "03-08": 1, "05-01": 1,
    "05-09": 1, "07-03": 1, "11-07": 1, "12-25": 1,
  };

  function pad2(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function toIso(d) {
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }

  function parseIsoLocal(s) {
    if (!s) return null;
    var p = String(s).split("-");
    if (p.length < 3) return null;
    return new Date(+p[0], +p[1] - 1, +p[2], 12, 0, 0);
  }

  function createTaskDateDuration(options) {
    var startEl = options.startEl;
    var dueEl = options.dueEl;
    var durationEl = options.durationEl;
    if (!startEl || !dueEl || !durationEl) return null;

    var skipWeekends = !!options.skipWeekends;
    var skipHolidays = !!options.skipHolidays;
    var dateMin = options.dateMin || "";
    var dateMax = options.dateMax || "";
    var syncing = false;

    function usesWorkCal() {
      return skipWeekends || skipHolidays;
    }

    function isNonWorking(d) {
      var wd = d.getDay();
      if (skipWeekends && (wd === 0 || wd === 6)) return true;
      if (skipHolidays) {
        var key = pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
        if (HOLIDAY_MD[key]) return true;
      }
      return false;
    }

    function snapToWorkday(d) {
      if (!usesWorkCal()) return d;
      var cur = new Date(d.getTime());
      var guard = 0;
      while (isNonWorking(cur) && guard < 800) {
        cur.setDate(cur.getDate() + 1);
        guard += 1;
      }
      return cur;
    }

    function addStepsFromDate(d, steps) {
      if (steps <= 0) return new Date(d.getTime());
      if (!usesWorkCal()) {
        var r = new Date(d.getTime());
        r.setDate(r.getDate() + steps);
        return r;
      }
      var cur = new Date(d.getTime());
      var added = 0;
      var guard = 0;
      while (added < steps && guard < 4000) {
        cur.setDate(cur.getDate() + 1);
        guard += 1;
        if (!isNonWorking(cur)) added += 1;
      }
      return cur;
    }

    function clampIso(iso) {
      if (!iso) return iso;
      if (dateMin && iso < dateMin) iso = dateMin;
      if (dateMax && iso > dateMax) iso = dateMax;
      return iso;
    }

    function countInclusive(startIso, endIso) {
      var a = parseIsoLocal(startIso);
      var b = parseIsoLocal(endIso);
      if (!a || !b || b < a) return 1;
      if (!usesWorkCal()) {
        return Math.max(1, Math.round((b - a) / 86400000) + 1);
      }
      var n = 0;
      var cur = new Date(a.getTime());
      var guard = 0;
      while (cur <= b && guard < 4000) {
        if (!isNonWorking(cur)) n += 1;
        cur.setDate(cur.getDate() + 1);
        guard += 1;
      }
      return Math.max(1, n);
    }

    function readDuration() {
      var n = parseInt(durationEl.value, 10);
      if (!isFinite(n) || n < 1) return 1;
      return Math.min(9999, n);
    }

    function recalcDueFromDuration() {
      if (syncing) return;
      var startIso = startEl.value;
      if (!startIso) return;
      var dur = readDuration();
      syncing = true;
      durationEl.value = String(dur);
      var sd = snapToWorkday(parseIsoLocal(startIso));
      var startFixed = clampIso(toIso(sd));
      var dueD = addStepsFromDate(sd, dur - 1);
      var dueIso = clampIso(toIso(dueD));
      if (dueIso < startFixed) dueIso = startFixed;
      startEl.value = startFixed;
      dueEl.value = dueIso;
      syncing = false;
    }

    function recalcDurationFromDue() {
      if (syncing) return;
      if (!startEl.value || !dueEl.value) return;
      syncing = true;
      durationEl.value = String(countInclusive(startEl.value, dueEl.value));
      syncing = false;
    }

    startEl.addEventListener("change", recalcDueFromDuration);
    durationEl.addEventListener("input", recalcDueFromDuration);
    durationEl.addEventListener("change", recalcDueFromDuration);
    dueEl.addEventListener("change", recalcDurationFromDue);

    if (startEl.value && dueEl.value) recalcDurationFromDue();
    else if (startEl.value) recalcDueFromDuration();

    return {
      recalcDueFromDuration: recalcDueFromDuration,
      recalcDurationFromDue: recalcDurationFromDue,
      countInclusive: countInclusive,
    };
  }

  global.createTaskDateDuration = createTaskDateDuration;
})(window);
