(function () {
  var dialog = document.getElementById("confirm-modal");
  if (!dialog || typeof dialog.showModal !== "function") return;

  var titleEl = document.getElementById("confirm-modal-title");
  var messageEl = document.getElementById("confirm-modal-message");
  var confirmBtn = document.getElementById("confirm-modal-confirm");
  var cancelBtn = document.getElementById("confirm-modal-cancel");
  var pendingForm = null;

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.confirmed === "true") {
      delete form.dataset.confirmed;
      return;
    }
    var message = form.getAttribute("data-confirm-message");
    if (!message) return;

    event.preventDefault();
    pendingForm = form;
    titleEl.textContent = form.getAttribute("data-confirm-title") || "Please confirm";
    messageEl.textContent = message;
    dialog.showModal();
  });

  confirmBtn.addEventListener("click", function () {
    dialog.close();
    if (pendingForm) {
      var form = pendingForm;
      pendingForm = null;
      form.dataset.confirmed = "true";
      if (form.requestSubmit) {
        form.requestSubmit();
      } else {
        form.submit();
      }
    }
  });

  cancelBtn.addEventListener("click", function () {
    dialog.close();
    pendingForm = null;
  });

  dialog.addEventListener("cancel", function () {
    pendingForm = null;
  });
})();
