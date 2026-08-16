(function () {
  var container = document.getElementById("history-rows");
  var refreshButton = document.getElementById("refresh-history");
  var status = document.getElementById("history-status");
  if (!container || !refreshButton) return;

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
    return fetch("/history/rows?page=" + encodeURIComponent(page))
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

  refreshButton.addEventListener("click", refresh);
  managePolling();
})();
