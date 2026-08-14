(function () {
  var list = document.getElementById("email-recipients");
  if (!list) return;

  var template = document.getElementById("email-recipient-template");
  var addButton = document.getElementById("add-recipient");

  function wireRemove(row) {
    row.querySelector(".remove-recipient").addEventListener("click", function () {
      if (list.querySelectorAll(".recipient-row").length > 1) {
        row.remove();
      } else {
        row.querySelector("input").value = "";
      }
    });
  }

  list.querySelectorAll(".recipient-row").forEach(wireRemove);

  addButton.addEventListener("click", function () {
    var row = template.content.firstElementChild.cloneNode(true);
    list.appendChild(row);
    wireRemove(row);
    row.querySelector("input").focus();
  });
})();
