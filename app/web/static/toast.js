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
