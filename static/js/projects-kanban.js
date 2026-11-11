(function () {
  const root = document.querySelector("[data-kanban-root]");
  if (!root) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const role = root.dataset.kanbanRole || "executor";
  const currentUserId = root.dataset.userId || "";
  let dragId = null;
  let dragFromStatus = null;
  let dragCard = null;

  function uiAlert(message, title) {
    if (typeof window.ssAlert === "function") {
      return window.ssAlert(message, { title: title || "Внимание" });
    }
    window.alert(message);
    return Promise.resolve(true);
  }

  function uiConfirm(message, options) {
    if (typeof window.ssConfirm === "function") {
      return window.ssConfirm(message, options || {});
    }
    return Promise.resolve(window.confirm(message));
  }

  root.querySelectorAll("[data-task-id][draggable='true']").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      dragId = card.dataset.taskId;
      dragFromStatus = card.dataset.kanbanStatus;
      dragCard = card;
      e.dataTransfer.effectAllowed = "move";
      card.classList.add("is-dragging");
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      dragId = null;
      dragFromStatus = null;
      dragCard = null;
    });
  });

  function adjacentOk(from, to) {
    const map = {
      todo: ["in_progress", "rejected", "archived"],
      in_progress: ["todo", "review", "rejected", "archived"],
      review: ["in_progress", "done", "rejected", "archived"],
      done: ["review", "archived"],
      rejected: ["todo", "in_progress", "archived"],
      archived: ["todo", "in_progress", "review", "done", "rejected"],
    };
    if (from === to) return true;
    return (map[from] || []).indexOf(to) !== -1;
  }

  function isOwnCard(card) {
    if (card.dataset.own === "1") return true;
    if (!card.dataset.assigneeId || !currentUserId) return false;
    return String(card.dataset.assigneeId) === String(currentUserId);
  }

  function roleClientOk(from, to, card) {
    if (!adjacentOk(from, to)) return false;
    const key = from + "|" + to;
    const own = isOwnCard(card);

    if (role === "admin") return true;

    if (role === "auditor") {
      if (own) {
        const allowedOwn = {
          "todo|in_progress": 1,
          "in_progress|todo": 1,
          "in_progress|review": 1,
          "review|in_progress": 1,
          "review|done": 1,
          "done|review": 1,
        };
        return !!allowedOwn[key];
      }
      const allowedOther = {
        "review|done": 1,
        "review|in_progress": 1,
        "done|review": 1,
        "review|rejected": 1,
        "done|archived": 1,
        "rejected|archived": 1,
        "archived|done": 1,
        "archived|review": 1,
        "archived|todo": 1,
        "archived|in_progress": 1,
        "archived|rejected": 1,
      };
      return !!allowedOther[key];
    }

    const allowedExec = {
      "todo|in_progress": 1,
      "in_progress|todo": 1,
      "in_progress|review": 1,
      "review|in_progress": 1,
    };
    return !!allowedExec[key];
  }

  root.querySelectorAll(".projects-kanban-drop").forEach((zone) => {
    zone.addEventListener("dragover", (e) => {
      if (zone.dataset.kanbanLocked === "1") return;
      e.preventDefault();
      zone.classList.add("is-drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-drag-over"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("is-drag-over");
      // dragend обнуляет глобальные drag* сразу после drop — копируем до await
      const card = dragCard;
      const taskId = dragId;
      const fromStatus = dragFromStatus;
      if (!taskId || !card) return;
      if (zone.dataset.kanbanLocked === "1") {
        await uiAlert("Колонка «В ожидании» управляется системой (блокирующие связи).");
        return;
      }
      const status = zone.dataset.kanbanStatus;
      if (!status || status === "waiting") return;
      if (!adjacentOk(fromStatus, status)) {
        await uiAlert("Нельзя перемещать задачу через шаг. Допустимы только соседние статусы.");
        return;
      }
      if (!roleClientOk(fromStatus, status, card)) {
        if (role === "auditor" && !isOwnCard(card) && (fromStatus === "todo" || fromStatus === "in_progress" || status === "todo" || status === "in_progress")) {
          await uiAlert("Чужие задачи в «К исполнению» / «В работе» аудитор только просматривает.");
        } else {
          await uiAlert("Это перемещение запрещено для вашей роли.");
        }
        return;
      }
      if (fromStatus === status) return;

      const body = { status: status, sort: 0 };
      const prevParent = card.parentElement;
      const prevNext = card.nextElementSibling;

      function restoreCard() {
        if (!prevParent) return;
        if (prevNext && prevNext.parentElement === prevParent) {
          prevParent.insertBefore(card, prevNext);
        } else {
          prevParent.appendChild(card);
        }
      }

      zone.prepend(card);

      try {
        let res = await fetch("/projects/api/tasks/" + taskId + "/move", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify(body),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (_) {}

        if (res.status === 422 && data.error === "need_report") {
          const ok = await uiConfirm("Выполнить задачу без отчёта?", {
            title: "Отчёт о выполнении",
            confirmLabel: "Без отчёта",
            cancelLabel: "Заполнить отчёт",
          });
          if (!ok) {
            restoreCard();
            window.location.href =
              "/projects/tasks/" + taskId + "?highlight=report#task-report";
            return;
          }
          body.force_empty_report = true;
          res = await fetch("/projects/api/tasks/" + taskId + "/move", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            body: JSON.stringify(body),
          });
          try {
            data = await res.json();
          } catch (_) {}
        }

        if (!res.ok) {
          restoreCard();
          const msgs = {
            blocked: "Задача заблокирована связями — сначала завершите предшественников.",
            skip: "Нельзя перемещать через шаг.",
            forbidden: "Это перемещение запрещено для вашей роли.",
            waiting_readonly: "Колонка «В ожидании» только для чтения.",
          };
          await uiAlert(msgs[data.error] || "Не удалось переместить задачу.");
          return;
        }
        const nextStatus = data.status || status;
        card.dataset.kanbanStatus = nextStatus;
        card.dataset.boardColumn = nextStatus;
      } catch (_) {
        restoreCard();
        await uiAlert("Ошибка сети при перемещении.");
      }
    });
  });
})();
