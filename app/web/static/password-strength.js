/* Advisory password-strength meter (#269).
 *
 * Attaches to every [data-password-strength="<input id>"] container rendered
 * by _password_strength.html. The result is announced as *text* in a polite
 * live region (the coloured bar is aria-hidden decoration), so it works with
 * screen readers and without colour vision. It never blocks submission --
 * the server-side policy (app/security/password_policy.py) is the rule; this
 * is only a nudge toward longer passphrases. Not loaded on the login page.
 */
(function () {
  "use strict";

  var LEVELS = [
    { label: "Very weak", tip: "Easy to guess. Try a longer passphrase." },
    { label: "Weak", tip: "Add more length; a few unrelated words work well." },
    { label: "Fair", tip: "OK, but a little more length would make it much stronger." },
    { label: "Strong", tip: "Good choice." },
    { label: "Very strong", tip: "Excellent." }
  ];

  function poolSize(pw) {
    var size = 0;
    if (/[a-z]/.test(pw)) size += 26;
    if (/[A-Z]/.test(pw)) size += 26;
    if (/[0-9]/.test(pw)) size += 10;
    if (/[ ]/.test(pw)) size += 1;
    if (/[^a-zA-Z0-9 ]/.test(pw)) size += 33;
    return Math.max(size, 1);
  }

  // Rough guess-resistance in bits, discounted for the patterns attackers try
  // first (repeats, runs, context words). Deliberately conservative.
  function estimateBits(pw, contextWords) {
    var chars = Array.from(pw);
    var unique = new Set(chars.map(function (c) { return c.toLowerCase(); })).size;
    var effectiveLen = Math.min(chars.length, unique * 2);
    var runs = 0;
    for (var i = 1; i < chars.length; i++) {
      var d = chars[i].charCodeAt(0) - chars[i - 1].charCodeAt(0);
      if (d === 1 || d === -1 || d === 0) runs++;
    }
    effectiveLen -= runs / 2;
    var bits = Math.max(effectiveLen, 0) * Math.log2(poolSize(pw));
    var lower = pw.toLowerCase();
    for (var j = 0; j < contextWords.length; j++) {
      var w = contextWords[j];
      if (w && w.length >= 3 && lower.indexOf(w) !== -1) bits = Math.min(bits, 20);
    }
    return bits;
  }

  function score(pw, minLen, contextWords) {
    var bits = estimateBits(pw, contextWords);
    var level = bits < 28 ? 0 : bits < 40 ? 1 : bits < 60 ? 2 : bits < 80 ? 3 : 4;
    if (Array.from(pw).length < minLen) level = 0;
    return level;
  }

  function attach(container) {
    var input = document.getElementById(container.getAttribute("data-password-strength"));
    if (!input) return;
    var text = container.querySelector(".pw-strength-text");
    var minLen = parseInt(input.getAttribute("minlength"), 10) || 8;
    var contextIds = (container.getAttribute("data-context-fields") || "").split(/\s+/);

    function contextWords() {
      return contextIds.map(function (id) {
        var el = id && document.getElementById(id);
        return el ? el.value.trim().toLowerCase() : "";
      });
    }

    function update() {
      var pw = input.value;
      if (!pw) {
        container.removeAttribute("data-level");
        text.textContent = "";
        return;
      }
      var len = Array.from(pw).length;
      var level = score(pw, minLen, contextWords());
      container.setAttribute("data-level", String(level));
      var msg = "Strength: " + LEVELS[level].label + ". ";
      msg += len < minLen
        ? (minLen - len) + " more character" + (minLen - len === 1 ? "" : "s") + " needed."
        : LEVELS[level].tip;
      text.textContent = msg;
    }

    container.hidden = false;
    input.addEventListener("input", update);
    update();
  }

  window.CareerSpyderPasswordStrength = { score: score };

  document.addEventListener("DOMContentLoaded", function () {
    var nodes = document.querySelectorAll("[data-password-strength]");
    for (var i = 0; i < nodes.length; i++) attach(nodes[i]);
  });
})();
