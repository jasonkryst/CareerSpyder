window.CareerSpyderMap = (function () {
  const HOME_LOCATION = { lat: 41.6412, lng: -88.4487, label: "Home — Yorkville, IL" };

  const homeIcon = L.divIcon({
    className: "home-marker",
    html: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="30" height="30">'
      + '<path fill="#2e7d32" stroke="#ffffff" stroke-width="1" stroke-linejoin="round" '
      + 'd="M12 2.7 2.5 10.8V21h6v-6.5h7V21h6V10.8z"/></svg>',
    iconSize: [30, 30],
    iconAnchor: [15, 28],
    popupAnchor: [0, -26],
  });

  function escapeHtml(value) {
    const str = value === null || value === undefined ? "" : String(value);
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  const overrideIcon = " &#9998;";

  function popupHtml(location) {
    const items = location.jobs
      .map(function (job) {
        const title = escapeHtml(job.title);
        const company = escapeHtml(job.company || "—");
        const url = escapeHtml(job.url);
        const badge = job.is_overridden
          ? "<span title=\"Location manually overridden\">" + overrideIcon + "</span> "
          : "";
        return "<li>" + badge + "<a href=\"" + url + "\" target=\"_blank\" rel=\"noopener noreferrer\">"
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
    const boundsPoints = [[HOME_LOCATION.lat, HOME_LOCATION.lng]];
    locations.forEach(function (location) {
      const marker = L.marker([location.lat, location.lng]);
      marker.bindPopup(popupHtml(location));
      cluster.addLayer(marker);
      boundsPoints.push([location.lat, location.lng]);
    });
    map.addLayer(cluster);

    L.marker([HOME_LOCATION.lat, HOME_LOCATION.lng], { icon: homeIcon, zIndexOffset: 1000 })
      .bindPopup(escapeHtml(HOME_LOCATION.label))
      .addTo(map);

    map.fitBounds(L.latLngBounds(boundsPoints), { padding: [40, 40], maxZoom: 12 });
  }

  return { renderMap: renderMap };
})();
