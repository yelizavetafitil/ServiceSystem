(function () {
  const root = document.querySelector("[data-kanban-root]");
  if (!root) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let dragId = null;

  root.querySelectorAll("[data-task-id]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      dragId = card.dataset.taskId;
      e.dataTransfer.effectAllowed = "move";
    });
  });

  root.querySelectorAll("[data-kanban-status]").forEach((zone) => {
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("is-drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-drag-over"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("is-drag-over");
      if (!dragId) return;
      const status = zone.dataset.kanbanStatus;
      const card = root.querySelector(`[data-task-id="${dragId}"]`);
      if (card) zone.prepend(card);
      card.dataset.kanbanStatus = status;
      await fetch(`/projects/api/tasks/${dragId}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ status, sort: 0 }),
      });
    });
  });
})();
