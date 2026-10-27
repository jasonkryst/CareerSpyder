(function () {
  var dialog = document.getElementById("confirm-modal");
  if (!dialog) return;

  // U6: older browsers without <dialog>/showModal used to lose the
  // confirmation entirely (the whole listener setup bailed out below,
  // so a destructive form just submitted immediately). Fail safe with
  // window.confirm() instead when showModal isn't available.
  var dialogSupported = typeof dialog.showModal === "function";

  var titleEl = document.getElementById("confirm-modal-title");
  var messageEl = document.getElementById("confirm-modal-message");
  var confirmBtn = document.getElementById("confirm-modal-confirm");
  var cancelBtn = document.getElementById("confirm-modal-cancel");
  var pendingForm = null;

  function submitConfirmed(form) {
    form.dataset.confirmed = "true";
    if (form.requestSubmit) {
      form.requestSubmit();
    } else {
      form.submit();
    }
  }

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

    if (!dialogSupported) {
      if (window.confirm(message)) {
        // Deferred: calling requestSubmit() synchronously here, still
        // inside this submit event's own call stack (window.confirm()
        // blocks but doesn't unwind it), re-enters form submission and
        // the browser silently drops it. A macrotask tick lets this
        // event finish dispatching first.
        setTimeout(function () { submitConfirmed(form); }, 0);
      }
      return;
    }

    pendingForm = form;
    titleEl.textContent = form.getAttribute("data-confirm-title") || "Please confirm";
    messageEl.textContent = message;
    dialog.showModal();
  });

  if (!dialogSupported) return;

  confirmBtn.addEventListener("click", function () {
    dialog.close();
    if (pendingForm) {
      var form = pendingForm;
      pendingForm = null;
      submitConfirmed(form);
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
