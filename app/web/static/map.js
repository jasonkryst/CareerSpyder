(function () {
  const container = document.getElementById("map");
  if (!container) return;

  fetch(container.dataset.jobsUrl)
    .then(function (resp) { return resp.json(); })
    .then(function (locations) {
      window.CareerSpyderMap.renderMap("map", locations);
    });
})();
