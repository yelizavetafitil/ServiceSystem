/**
 * Общее дерево проекта: карточка задачи, форма создания.
 * mode=nav — двойной клик открывает; mode=create — выбор этапа, DnD в «Выполнить после».
 */
(function (global) {
  var staleModal = document.getElementById("task-editor-modal");
  if (staleModal) staleModal.remove();
  if (document.body) document.body.classList.remove("projects-task-editor-open");

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function buildChildrenMap(tasks) {
    var byParent = {};
    (tasks || []).forEach(function (t) {
      var key = t.parent_id == null ? "root" : String(t.parent_id);
      if (!byParent[key]) byParent[key] = [];
      byParent[key].push(t);
    });
    return byParent;
  }

  function taskNewHref(projectId, armView, opts) {
    opts = opts || {};
    var href = "/projects/tasks/new?project=" + encodeURIComponent(projectId || "");
    if (opts.parent) href += "&parent=" + encodeURIComponent(opts.parent);
    if (opts.stage) href += "&stage=" + encodeURIComponent(opts.stage);
    if (armView) href += "&arm_view=" + encodeURIComponent(armView);
    return href;
  }

  function draftNodeHtml(label) {
    return (
      '<li class="projects-task-tree-item projects-task-tree-item--draft">' +
      '<span class="projects-task-tree-draft">' +
      esc(label || "Новые задачи…") +
      "</span></li>"
    );
  }

  function renderTaskNodes(tasks, byParent, depth, opts) {
    var html = "";
    var currentId = opts.currentId || "";
    var highlightParentId = opts.highlightParentId || "";
    var canCreate = !!opts.canCreate;
    var draggable = !!opts.draggable;
    var projectId = opts.projectId || "";
    var armView = opts.armView || "";

    (tasks || []).forEach(function (t) {
      var isCur = currentId && String(t.id) === String(currentId);
      var isParent = highlightParentId && String(t.id) === String(highlightParentId);
      var tip = t.title + (t.dates_label ? " · " + t.dates_label : "");
      html +=
        '<li class="projects-task-tree-item projects-task-tree-item--task' +
        (isCur ? " is-current" : "") +
        (isParent ? " is-parent-of-new" : "") +
        '" style="--depth:' +
        depth +
        '">';
      html += '<div class="projects-task-tree-row">';
      html +=
        '<a class="projects-task-tree-link' +
        (isCur ? " is-current" : "") +
        '" href="/projects/tasks/' +
        t.id +
        '"' +
        (draggable
          ? ' draggable="true" data-task-id="' +
            t.id +
            '" data-due="' +
            esc(t.due || "") +
            '" data-start="' +
            esc(t.start || "") +
            '" data-title="' +
            esc(t.title) +
            '"'
          : "") +
        ' title="' +
        esc(tip) +
        (draggable ? " · перетащите в «Выполнить после»" : "") +
        ' · двойной клик — открыть">' +
        '<span class="projects-task-tree-name">';
      if (t.wbs) {
        html +=
          '<span class="projects-task-tree-wbs" title="WBS ' +
          esc(t.wbs) +
          '">' +
          esc(t.wbs) +
          "</span> ";
      }
      html += esc(t.title) + "</span>";
      if (t.dates_label) {
        html += '<span class="projects-task-tree-dates">' + esc(t.dates_label) + "</span>";
      }
      html += "</a>";
      if (canCreate) {
        html +=
          '<button type="button" class="projects-task-tree-edit" data-task-id="' +
          esc(String(t.id)) +
          '" title="Редактировать" aria-label="Редактировать задачу">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>' +
          "</button>" +
          '<button type="button" class="projects-task-tree-delete" data-task-id="' +
          esc(String(t.id)) +
          '" data-task-title="' +
          esc(t.title) +
          '" title="Удалить" aria-label="Удалить задачу">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>' +
          "</button>";
      }
      if (canCreate && projectId) {
        html +=
          '<a class="projects-task-tree-add" href="' +
          taskNewHref(projectId, armView, { parent: t.id }) +
          '" title="Добавить подзадачу" aria-label="Добавить подзадачу">＋</a>';
      }
      html += "</div>";
      var kids = byParent[String(t.id)] || [];
      var showDraftHere = isParent && opts.mode === "create";
      if (kids.length || showDraftHere) {
        html += '<ul class="projects-task-tree-list">';
        html += renderTaskNodes(kids, byParent, depth + 1, opts);
        if (showDraftHere) html += draftNodeHtml(opts.draftLabel);
        html += "</ul>";
      }
      html += "</li>";
    });
    return html;
  }

  function stageHeaderHtml(sid, titleHtml, deadlineLabel, opts) {
    var stageId = opts.stageId || "";
    var active =
      String(sid) === String(stageId) || (sid === "" && !stageId && opts.mode === "create");
    var canCreate = !!opts.canCreate;
    var projectId = opts.projectId || "";
    var armView = opts.armView || "";
    var html = '<div class="projects-task-tree-stage-row">';

    if (opts.mode === "create") {
      html +=
        '<button type="button" class="projects-task-tree-stage" data-stage-id="' +
        esc(String(sid)) +
        '">';
      html += '<span class="projects-task-tree-stage-title">' + titleHtml + "</span>";
      if (deadlineLabel) {
        html += '<span class="projects-task-tree-dates">до ' + esc(deadlineLabel) + "</span>";
      }
      html += "</button>";
      html +=
        '<button type="button" class="projects-task-tree-add projects-task-tree-add--stage' +
        (active ? " is-lit" : "") +
        '" data-stage-id="' +
        esc(String(sid)) +
        '" title="Создать задачу" aria-label="Создать задачу">＋</button>';
    } else {
      html += '<div class="projects-task-tree-stage projects-task-tree-stage--static">';
      html += '<span class="projects-task-tree-stage-title">' + titleHtml + "</span>";
      if (deadlineLabel) {
        html += '<span class="projects-task-tree-dates">до ' + esc(deadlineLabel) + "</span>";
      }
      html += "</div>";
      if (canCreate && projectId) {
        html +=
          '<a class="projects-task-tree-add projects-task-tree-add--stage is-lit" href="' +
          taskNewHref(projectId, armView, sid ? { stage: sid } : {}) +
          '" title="Создать задачу" aria-label="Создать задачу">＋</a>';
      }
    }
    html += "</div>";
    return html;
  }

  /** Универсальный рендер. options: mode, stages, tasks, projectName, projectDates, ... */
  function renderProjectTree(rootEl, options) {
    if (!rootEl) return;
    var opts = options || {};
    opts.mode = opts.mode || "nav";
    opts.projectId = opts.projectId || "";
    opts.armView = opts.armView || "";
    opts.canCreate = opts.canCreate !== false && !!opts.projectId;
    opts.draggable = opts.mode === "create" ? opts.draggable !== false : !!opts.draggable;
    opts.stageId = opts.stageId || "";
    opts.currentId = opts.currentId || "";
    opts.highlightParentId = opts.highlightParentId || "";
    opts.draftLabel = opts.draftLabel || "Новые задачи…";

    var stages = opts.stages || [];
    var tasks = opts.tasks || [];
    var byParent = buildChildrenMap(tasks);
    var nestDraftUnderParent = opts.mode === "create" && !!opts.highlightParentId;
    var stageId = opts.stageId;

    function rootsForStage(sid) {
      return (byParent.root || []).filter(function (t) {
        if (sid === "") return !t.stage_id;
        return String(t.stage_id) === String(sid);
      });
    }

    var html = '<ul class="projects-task-tree-list projects-task-tree-list--root">';
    html += '<li class="projects-task-tree-item projects-task-tree-item--project">';
    html +=
      '<div class="projects-task-tree-project-row">' +
      '<span class="projects-task-tree-label projects-task-tree-label--project">' +
      esc(opts.projectName || "Проект");
    if (opts.projectDates) {
      html += '<span class="projects-task-tree-dates">' + esc(opts.projectDates) + "</span>";
    }
    html += "</span>";
    if (opts.canCreate && opts.projectId && opts.mode === "nav") {
      html +=
        '<a class="projects-task-tree-add projects-task-tree-add--project is-lit" href="' +
        taskNewHref(opts.projectId, opts.armView, {}) +
        '" title="Создать задачу" aria-label="Создать задачу">＋</a>';
    }
    html += "</div>";
    html += '<ul class="projects-task-tree-list">';

    stages.forEach(function (s) {
      var active = String(s.id) === String(stageId);
      html +=
        '<li class="projects-task-tree-item projects-task-tree-item--stage' +
        (opts.mode === "create" && active ? " is-active" : "") +
        '">';
      html += stageHeaderHtml(s.id, esc(s.title), s.deadline_label || "", opts);
      html += '<ul class="projects-task-tree-list">';
      html += renderTaskNodes(rootsForStage(s.id), byParent, 1, opts);
      if (opts.mode === "create" && active && !nestDraftUnderParent) {
        html += draftNodeHtml(opts.draftLabel);
      }
      html += "</ul></li>";
    });

    var unstaged = rootsForStage("");
    var unstagedActive = !stageId;
    var showUnstaged =
      unstaged.length ||
      (opts.mode === "create" && (unstagedActive || !stages.length)) ||
      (opts.mode === "nav" && (unstaged.length || (opts.canCreate && !stages.length)));
    if (showUnstaged) {
      html +=
        '<li class="projects-task-tree-item projects-task-tree-item--stage' +
        (opts.mode === "create" && unstagedActive ? " is-active" : "") +
        '">';
      html += stageHeaderHtml("", "Без этапа", "", opts);
      html += '<ul class="projects-task-tree-list">';
      html += renderTaskNodes(unstaged, byParent, 1, opts);
      if (opts.mode === "create" && unstagedActive && !nestDraftUnderParent) {
        html += draftNodeHtml(opts.draftLabel);
      }
      html += "</ul></li>";
    }

    html += "</ul></li></ul>";
    rootEl.innerHTML = html;
    bindTaskEditor(rootEl);
  }

  function openTaskEditor(taskId) {
    if (!taskId) return;
    window.location.assign("/projects/tasks/" + encodeURIComponent(taskId));
  }

  function deleteTreeTask(taskId, title) {
    if (!taskId) return;
    var message = "Удалить задачу «" + title + "»? Подзадачи останутся в проекте отдельными задачами.";
    var run = function () {
      var tokenEl = document.querySelector('input[name="csrf_token"]');
      var body = new URLSearchParams();
      if (tokenEl) body.set("csrf_token", tokenEl.value);
      body.set("action", "delete");
      fetch("/projects/tasks/" + encodeURIComponent(taskId), {
        method: "POST",
        body: body,
        credentials: "same-origin",
        redirect: "follow",
      }).then(function () {
        window.location.reload();
      });
    };
    if (window.ssConfirm) {
      window.ssConfirm(message, {
        title: "Удаление задачи",
        confirmLabel: "Удалить",
        danger: true,
      }).then(function (ok) {
        if (ok) run();
      });
      return;
    }
    if (window.confirm(message)) run();
  }

  function bindTaskEditor(rootEl) {
    if (!rootEl || rootEl.getAttribute("data-task-editor") === "1") return;
    rootEl.setAttribute("data-task-editor", "1");
    rootEl.addEventListener("click", function (e) {
      var del = e.target.closest && e.target.closest(".projects-task-tree-delete");
      if (del && rootEl.contains(del)) {
        e.preventDefault();
        e.stopPropagation();
        deleteTreeTask(del.getAttribute("data-task-id"), del.getAttribute("data-task-title") || "");
        return;
      }
      var btn = e.target.closest && e.target.closest(".projects-task-tree-edit");
      if (!btn || !rootEl.contains(btn)) return;
      e.preventDefault();
      e.stopPropagation();
      openTaskEditor(btn.getAttribute("data-task-id"));
    });
  }

  function readJsonScript(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      return null;
    }
  }

  function bindDoubleClickNav(rootEl) {
    if (!rootEl || rootEl.getAttribute("data-dblclick-nav") === "1") return;
    rootEl.setAttribute("data-dblclick-nav", "1");
    rootEl.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("a.projects-task-tree-add")) return;
      if (e.target.closest && e.target.closest("button.projects-task-tree-add")) return;
      if (e.target.closest && e.target.closest("button.projects-task-tree-edit")) return;
      if (e.target.closest && e.target.closest("button.projects-task-tree-delete")) return;
      var link = e.target.closest && e.target.closest("a.projects-task-tree-link");
      if (!link || !rootEl.contains(link)) return;
      e.preventDefault();
      rootEl.querySelectorAll(".projects-task-tree-link.is-selected").forEach(function (a) {
        a.classList.remove("is-selected");
      });
      if (!link.classList.contains("is-current")) link.classList.add("is-selected");
    });
    rootEl.addEventListener("dblclick", function (e) {
      var link = e.target.closest && e.target.closest("a.projects-task-tree-link");
      if (!link || !rootEl.contains(link)) return;
      e.preventDefault();
      var href = link.getAttribute("href");
      if (href) window.location.href = href;
    });
  }

  /** Карточка задачи: json-скрипты + data-* на root. */
  function renderProjectTreeNav(rootEl) {
    if (!rootEl) return;
    var project = readJsonScript("task-tree-project-json") || {};
    renderProjectTree(rootEl, {
      mode: "nav",
      currentId: rootEl.getAttribute("data-current-task-id") || "",
      projectId: rootEl.getAttribute("data-project-id") || "",
      armView: rootEl.getAttribute("data-arm-view") || "",
      canCreate: rootEl.getAttribute("data-can-create") !== "0",
      stages: readJsonScript("task-tree-stages-json") || [],
      tasks: readJsonScript("task-tree-tasks-json") || [],
      projectName: project.name || "Проект",
      projectDates: project.dates_label || "",
      draggable: false,
    });
    bindDoubleClickNav(rootEl);
  }

  global.renderProjectTree = renderProjectTree;
  global.renderProjectTreeNav = renderProjectTreeNav;
  global.bindProjectTreeDblClick = bindDoubleClickNav;
  global.openTaskEditor = openTaskEditor;
})(window);
