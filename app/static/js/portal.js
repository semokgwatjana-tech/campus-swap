(function () {
  var card = document.getElementById("portal");
  if (!card) { return; }

  var panes = { signin: document.getElementById("pane-signin"), signup: document.getElementById("pane-signup") };
  var copies = { signin: card.querySelector(".copy-in"), signup: card.querySelector(".copy-up") };
  var titles = { signin: "Sign in | Campus Swap", signup: "Create account | Campus Swap" };
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setMode(mode, focusFirst) {
    var other = mode === "signup" ? "signin" : "signup";
    card.classList.toggle("is-signup", mode === "signup");
    card.classList.toggle("is-signin", mode === "signin");
    panes[mode].removeAttribute("inert");
    panes[other].setAttribute("inert", "");
    copies[mode].setAttribute("aria-hidden", "false");
    copies[other].setAttribute("aria-hidden", "true");
    document.title = titles[mode];
    if (focusFirst) {
      var first = panes[mode].querySelector("input:not([type=hidden])");
      window.setTimeout(function () { if (first) { first.focus(); } }, reduce ? 0 : 450);
    }
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-switch]"), function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      var mode = link.getAttribute("data-switch");
      setMode(mode, true);
      history.pushState({ mode: mode }, "", link.getAttribute("href"));
    });
  });

  window.addEventListener("popstate", function () {
    setMode(/\/register\/?$/.test(location.pathname) ? "signup" : "signin", false);
  });

  // Show the parent or guardian fields only for someone under 18 (the server checks this too).
  var dob = document.querySelector("[data-dob]");
  var guardianBlock = document.getElementById("guardian-block");
  function updateGuardian() {
    if (!dob || !guardianBlock) { return; }
    var value = dob.value;
    if (!value) { guardianBlock.hidden = true; return; }
    var born = new Date(value + "T00:00:00");
    var today = new Date();
    var age = today.getFullYear() - born.getFullYear();
    var m = today.getMonth() - born.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < born.getDate())) { age -= 1; }
    guardianBlock.hidden = age >= 18;
  }
  if (dob) { dob.addEventListener("input", updateGuardian); dob.addEventListener("change", updateGuardian); updateGuardian(); }

  Array.prototype.forEach.call(document.querySelectorAll("[data-toggle-password]"), function (btn) {
    btn.addEventListener("click", function () {
      var input = btn.parentNode.querySelector("input");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.firstElementChild.className = show ? "bi bi-eye-slash" : "bi bi-eye";
    });
  });
})();
