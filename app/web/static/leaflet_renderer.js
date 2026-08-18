window.CareerSpyderMap = (function () {
  function escapeHtml(value) {
    const str = value === null || value === undefined ? "" : String(value);
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function popupHtml(location) {
    const items = location.jobs
      .map(function (job) {
        const title = escapeHtml(job.title);
        const company = escapeHtml(job.company || "—");
        const url = escapeHtml(job.url);
        return "<li><a href=\"" + url + "\" target=\"_blank\" rel=\"noopener noreferrer\">"
          + title + "</a> — " + company + "</li>";
      })
      .join("");
    return "<strong>" + escapeHtml(location.display_name) + "</strong><ul>" + items + "</ul>";
  }

  function renderMap(containerId, locations) {
    const map = L.map(containerId).setView([39.8283, -98.5795], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    const cluster = L.markerClusterGroup();
    locations.forEach(function (location) {
      const marker = L.marker([location.lat, location.lng]);
      marker.bindPopup(popupHtml(location));
      cluster.addLayer(marker);
    });
    map.addLayer(cluster);
  }

  return { renderMap: renderMap };
})();
