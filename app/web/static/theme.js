(function () {
  var toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  function currentTheme() {
    return (
      document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    );
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    toggle.setAttribute("aria-pressed", String(theme === "dark"));
    toggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  }

  applyTheme(currentTheme());

  toggle.addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    applyTheme(next);
  });
})();
