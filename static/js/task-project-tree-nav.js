(function (global) {
  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function buildChildrenMap(tasks) {
    var byParent = {};
    tasks.forEach(function (t) {
      var key = t.parent_id == null ? "root" : String(t.parent_id);
      if (!byParent[key]) byParent[key] = [];
      byParent[key].push(t);
    });
    return byParent;
  }

  function renderTaskNodes(tasks, byParent, depth, currentId) {
    var html = "";
    tasks.forEach(function (t) {
      var isCur = String(t.id) === String(currentId);
      var tip = t.title + (t.dates_label ? " · " + t.dates_label : "");
      html += '<li class="projects-task-tree-item projects-task-tree-item--task' +
        (isCur ? " is-current" : "") + '" style="--depth:' + depth + '">';
      html += '<div class="projects-task-tree-row">';
      html += '<a class="projects-task-tree-link' + (isCur ? " is-current" : "") +
        '" href="/projects/tasks/' + t.id + '" title="' + esc(tip) + '">';
      html += '<span class="projects-task-tree-name">' + esc(t.title) + "</span>";
      if (t.dates_label) {
        html += '<span class="projects-task-tree-dates">' + esc(t.dates_label) + "</span>";
      }
      html += "</a></div>";
      var kids = byParent[String(t.id)] || [];
      if (kids.length) {
        html += '<ul class="projects-task-tree-list">';
        html += renderTaskNodes(kids, byParent, depth + 1, currentId);
        html += "</ul>";
      }
      html += "</li>";
    });
    return html;
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

  function renderProjectTreeNav(rootEl) {
    if (!rootEl) return;
    var currentId = rootEl.getAttribute("data-current-task-id") || "";
    var stages = readJsonScript("task-tree-stages-json") || [];
    var tasks = readJsonScript("task-tree-tasks-json") || [];
    var project = readJsonScript("task-tree-project-json") || {};

    var byParent = buildChildrenMap(tasks);
    var pname = project.name || "Проект";
    var pdates = project.dates_label || "";

    var html = '<ul class="projects-task-tree-list projects-task-tree-list--root">';
    html += '<li class="projects-task-tree-item projects-task-tree-item--project">';
    html += '<span class="projects-task-tree-label projects-task-tree-label--project">' + esc(pname);
    if (pdates) html += '<span class="projects-task-tree-dates">' + esc(pdates) + "</span>";
    html += '</span><ul class="projects-task-tree-list">';

    stages.forEach(function (s) {
      var roots = (byParent.root || []).filter(function (t) {
        return String(t.stage_id) === String(s.id);
      });
      html += '<li class="projects-task-tree-item projects-task-tree-item--stage">';
      html += '<span class="projects-task-tree-stage-title">' + esc(s.title) + "</span>";
      if (s.deadline_label) {
        html += '<span class="projects-task-tree-dates">до ' + esc(s.deadline_label) + "</span>";
      }
      html += '<ul class="projects-task-tree-list">';
      html += renderTaskNodes(roots, byParent, 1, currentId);
      html += "</ul></li>";
    });

    var unstaged = (byParent.root || []).filter(function (t) {
      return !t.stage_id;
    });
    if (unstaged.length) {
      html += '<li class="projects-task-tree-item projects-task-tree-item--stage">';
      html += '<span class="projects-task-tree-stage-title">Без этапа</span>';
      html += '<ul class="projects-task-tree-list">';
      html += renderTaskNodes(unstaged, byParent, 1, currentId);
      html += "</ul></li>";
    }

    html += "</ul></li></ul>";
    rootEl.innerHTML = html;
  }

  global.renderProjectTreeNav = renderProjectTreeNav;
})(window);
