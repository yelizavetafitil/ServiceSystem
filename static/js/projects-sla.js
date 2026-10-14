(function () {
  function tick() {
    document.querySelectorAll("[data-deadline]").forEach(function (el) {
      var raw = el.getAttribute("data-deadline");
      if (!raw) return;
      var end = new Date(raw);
      var now = new Date();
      var ms = end - now;
      if (ms <= 0) {
        el.textContent = "Срок: просрочено";
        el.classList.add("is-overdue");
        return;
      }
      var h = Math.floor(ms / 3600000);
      var m = Math.floor((ms % 3600000) / 60000);
      el.textContent = "Срок: " + h + " ч " + m + " мин";
    });
  }
  tick();
  setInterval(tick, 60000);
})();
