(function () {
  var radios = document.querySelectorAll('input[name="theme"]');
  if (!radios.length) return;

  function storedTheme() {
    var stored = localStorage.getItem("theme");
    return stored === "light" || stored === "dark" ? stored : "system";
  }

  function applyTheme(theme) {
    if (theme === "system") {
      localStorage.removeItem("theme");
      document.documentElement.removeAttribute("data-theme");
    } else {
      localStorage.setItem("theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
    }
  }

  var current = storedTheme();
  radios.forEach(function (radio) {
    radio.checked = radio.value === current;
    radio.addEventListener("change", function () {
      if (radio.checked) applyTheme(radio.value);
    });
  });
})();
