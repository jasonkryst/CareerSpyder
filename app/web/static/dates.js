(function () {
  var formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

  function formatLocalDates(root) {
    root = root || document;
    var elements = root.querySelectorAll("time[datetime]");
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var date = new Date(el.getAttribute("datetime"));
      if (isNaN(date.getTime())) continue;
      el.textContent = formatter.format(date);
    }
  }

  window.formatLocalDates = formatLocalDates;
  formatLocalDates(document);
})();
