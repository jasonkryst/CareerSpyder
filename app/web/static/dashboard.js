(function () {
  var container = document.getElementById("history-rows");
  var refreshButton = document.getElementById("refresh-history");
  var status = document.getElementById("history-status");
  var runForm = document.getElementById("run-now-form");
  var runStatus = document.getElementById("run-now-status");
  if (!container) return;

  var POLL_MS = 10000;
  var pollTimer = null;

  function hasInProgressRun() {
    var cells = container.querySelectorAll('td[data-label="Finished"]');
    for (var i = 0; i < cells.length; i++) {
      if (cells[i].textContent.trim() === "in progress") return true;
    }
    return false;
  }

  function refresh() {
    var page = container.getAttribute("data-page") || "1";
    return fetch("/rows?page=" + encodeURIComponent(page))
      .then(function (resp) { return resp.text(); })
      .then(function (html) {
        var wrapper = document.createElement("div");
        wrapper.innerHTML = html;
        var next = wrapper.firstElementChild;
        container.replaceWith(next);
        container = next;
        if (status) status.textContent = "Updated";
        managePolling();
      });
  }

  function managePolling() {
    if (hasInProgressRun()) {
      if (!pollTimer) pollTimer = setInterval(refresh, POLL_MS);
    } else if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  if (refreshButton) refreshButton.addEventListener("click", refresh);

  if (runForm) {
    runForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = runForm.querySelector("button[type=submit]");
      if (button) button.disabled = true;
      if (runStatus) runStatus.textContent = "Starting run…";
      fetch(runForm.getAttribute("action"), { method: "POST" })
        .then(refresh)
        .then(function () {
          if (runStatus) runStatus.textContent = "Run started";
          if (button) button.disabled = false;
        });
    });
  }

  managePolling();
})();
