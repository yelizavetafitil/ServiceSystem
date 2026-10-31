/**
 * Видеоурок: полноэкранный режим с выезжающим оглавлением (тайм-коды).
 */
(function () {
  function parseChapters(raw) {
    if (!raw) return [];
    try {
      var data = JSON.parse(raw);
      return Array.isArray(data) ? data : [];
    } catch (e) {
      return [];
    }
  }

  function isYouTubeIframe(iframe) {
    if (!iframe || !iframe.src) return false;
    return /youtube\.com\/embed|youtube-nocookie\.com\/embed/i.test(iframe.src);
  }

  function ytCommand(iframe, func, args) {
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      JSON.stringify({ event: "command", func: func, args: args || [] }),
      "*"
    );
  }

  function formatTime(sec) {
    sec = Math.max(0, parseInt(sec, 10) || 0);
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function initShell(shell) {
    var chapters = parseChapters(shell.getAttribute("data-chapters"));
    var stage = shell.querySelector(".video-player-stage");
    var video = shell.querySelector("video.video-stream");
    var iframe = shell.querySelector(".video-player-wrap iframe");
    var panel = shell.querySelector(".video-player-chapters");
    var list = shell.querySelector(".video-player-chapters__list");
    var btnFs = shell.querySelector(".video-player-fs");
    var btnCh = shell.querySelector(".video-player-chapters-toggle");
    if (!stage || !panel || !list) return;

    var ytReady = false;
    if (iframe && isYouTubeIframe(iframe)) {
      iframe.addEventListener("load", function () {
        try {
          iframe.contentWindow.postMessage(
            '{"event":"listening","id":1,"channel":"widget"}',
            "*"
          );
        } catch (e) {}
      });
      window.addEventListener("message", function onYt(ev) {
        if (ev.source !== iframe.contentWindow) return;
        var data;
        try {
          data = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
        } catch (e) {
          return;
        }
        if (data && data.event === "onReady") {
          ytReady = true;
          window.removeEventListener("message", onYt);
        }
      });
    }

    function seekTo(sec) {
      sec = parseInt(sec, 10) || 0;
      if (video) {
        video.currentTime = sec;
        video.play().catch(function () {});
        return;
      }
      if (iframe && isYouTubeIframe(iframe)) {
        if (ytReady) {
          ytCommand(iframe, "seekTo", [sec, true]);
          ytCommand(iframe, "playVideo");
        } else {
          var url = new URL(iframe.src.split("?")[0], window.location.origin);
          var q = iframe.src.indexOf("?") >= 0 ? iframe.src.split("?")[1] : "";
          var params = new URLSearchParams(q);
          params.set("start", String(sec));
          params.set("autoplay", "1");
          iframe.src = url.pathname + "?" + params.toString();
        }
        return;
      }
      if (iframe) {
        var base = iframe.src.split("?")[0];
        var p2 = new URLSearchParams(iframe.src.split("?")[1] || "");
        p2.set("start", String(sec));
        iframe.src = base + "?" + p2.toString();
      }
    }

    function setActiveChapter(sec) {
      var activeIdx = -1;
      for (var i = chapters.length - 1; i >= 0; i--) {
        if ((chapters[i].start_sec || 0) <= sec) {
          activeIdx = i;
          break;
        }
      }
      list.querySelectorAll(".video-player-chapters__item").forEach(function (li, idx) {
        li.classList.toggle("is-active", idx === activeIdx);
      });
    }

    chapters.forEach(function (ch) {
      var li = document.createElement("li");
      li.className = "video-player-chapters__item";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "video-player-chapters__btn";
      btn.dataset.seek = String(ch.start_sec || 0);
      btn.innerHTML =
        '<span class="video-player-chapters__time">' +
        formatTime(ch.start_sec) +
        "</span>" +
        '<span class="video-player-chapters__title">' +
        (ch.title || "") +
        "</span>";
      if (ch.description) {
        var desc = document.createElement("p");
        desc.className = "video-player-chapters__desc";
        desc.textContent = ch.description;
        li.appendChild(btn);
        li.appendChild(desc);
      } else {
        li.appendChild(btn);
      }
      btn.addEventListener("click", function () {
        seekTo(btn.dataset.seek);
      });
      list.appendChild(li);
    });

    function toggleChapters(open) {
      var on = open !== undefined ? open : !shell.classList.contains("is-chapters-open");
      shell.classList.toggle("is-chapters-open", on);
      if (btnCh) btnCh.setAttribute("aria-expanded", on ? "true" : "false");
      panel.setAttribute("aria-hidden", on ? "false" : "true");
    }

    if (btnCh) {
      btnCh.addEventListener("click", function () {
        toggleChapters();
      });
    }

    shell.querySelectorAll(".video-player-chapters__close").forEach(function (btn) {
      btn.addEventListener("click", function () {
        toggleChapters(false);
      });
    });

    function isFs() {
      return (
        document.fullscreenElement === shell ||
        document.webkitFullscreenElement === shell
      );
    }

    function enterFs() {
      var req = shell.requestFullscreen || shell.webkitRequestFullscreen;
      if (req) req.call(shell);
    }

    function exitFs() {
      var ex = document.exitFullscreen || document.webkitExitFullscreen;
      if (ex && isFs()) ex.call(document);
    }

    if (btnFs) {
      btnFs.addEventListener("click", function () {
        if (isFs()) exitFs();
        else enterFs();
      });
    }

    document.addEventListener("fullscreenchange", syncFs);
    document.addEventListener("webkitfullscreenchange", syncFs);

    function syncFs() {
      var fs = isFs();
      shell.classList.toggle("is-fullscreen", fs);
      if (btnFs) {
        btnFs.setAttribute("aria-pressed", fs ? "true" : "false");
        btnFs.title = fs ? "Выйти из полноэкранного режима" : "На весь экран";
      }
    }

    if (video) {
      video.addEventListener("timeupdate", function () {
        setActiveChapter(Math.floor(video.currentTime || 0));
      });
    }

    shell.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && shell.classList.contains("is-chapters-open") && isFs()) {
        ev.stopPropagation();
        toggleChapters(false);
      }
    });
  }

  document.querySelectorAll(".video-player-shell").forEach(initShell);
})();
