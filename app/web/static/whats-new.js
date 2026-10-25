(function () {
  var trigger = document.getElementById("whats-new-trigger");
  var dialog = document.getElementById("whats-new-modal");
  var closeBtn = document.getElementById("whats-new-modal-close");
  if (!trigger || !dialog || typeof dialog.showModal !== "function") return;

  trigger.addEventListener("click", function () {
    dialog.showModal();
  });

  closeBtn.addEventListener("click", function () {
    dialog.close();
  });
})();
