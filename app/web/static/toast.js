(function () {
  var toast = document.querySelector(".toast");
  if (!toast) return;

  var timer = setTimeout(dismiss, 5000);

  function dismiss() {
    clearTimeout(timer);
    toast.remove();
    var url = new URL(window.location.href);
    url.searchParams.delete("flash");
    var next = url.pathname + (url.search || "") + url.hash;
    history.replaceState(null, "", next);
  }

  var closeBtn = toast.querySelector(".toast-close");
  if (closeBtn) closeBtn.addEventListener("click", dismiss);
})();

window.showToast = function (message) {
  var container = document.getElementById("toast-container");
  if (!container) return;
  var div = document.createElement("div");
  div.className = "toast";
  div.setAttribute("role", "status");
  div.textContent = message;
  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "toast-close";
  btn.setAttribute("aria-label", "Dismiss");
  btn.textContent = "×";
  div.appendChild(btn);
  container.appendChild(div);
  var t = setTimeout(function () { div.remove(); }, 5000);
  btn.addEventListener("click", function () { clearTimeout(t); div.remove(); });
};
