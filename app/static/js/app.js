/* Campus Swap: small site-wide behaviours. Everything here is attached with
   addEventListener, so the pages need no inline onclick/onchange handlers and the
   Content-Security-Policy can forbid them. */
(function () {
  "use strict";

  // A picture that fails to load is swapped once for the fallback named in data-fallback.
  document.addEventListener("error", function (event) {
    var el = event.target;
    if (el && el.tagName === "IMG" && el.dataset.fallback && !el.dataset.fallbackUsed) {
      el.dataset.fallbackUsed = "1";
      el.src = el.dataset.fallback;
    }
  }, true);

  // data-change="name": call window.name(value) when the field changes.
  document.addEventListener("change", function (event) {
    var el = event.target;
    var fn = el && el.dataset ? el.dataset.change : null;
    if (fn && typeof window[fn] === "function") { window[fn](el.value); }
  });

  document.addEventListener("click", function (event) {
    var el = event.target.closest ? event.target.closest("[data-click],[data-share-title]") : null;
    if (!el) { return; }
    if (el.dataset.click && typeof window[el.dataset.click] === "function") {
      window[el.dataset.click](el);
    }
    if (el.dataset.shareTitle !== undefined) {
      var data = { title: el.dataset.shareTitle, url: window.location.href };
      if (navigator.share) { navigator.share(data).catch(function () {}); }
      else { window.alert("Copy this link to share: " + window.location.href); }
    }
  });

  // data-confirm="question" on a form asks before it is sent.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form && form.dataset && form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  }, true);

  // A show/hide eye on every password field that does not already have one.
  function addReveal(input) {
    if (input.dataset.noReveal !== undefined || input.closest(".pt-input") || input.closest(".pw-wrap")) { return; }
    var wrap = document.createElement("span");
    wrap.className = "pw-wrap";
    var margin = window.getComputedStyle(input).marginBottom;
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    wrap.style.marginBottom = margin;
    input.style.marginBottom = "0";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "pw-toggle";
    button.setAttribute("aria-label", "Show password");
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.firstChild.className = show ? "bi bi-eye-slash" : "bi bi-eye";
    });
    wrap.appendChild(button);
  }
  Array.prototype.forEach.call(document.querySelectorAll('input[type="password"]'), addReveal);
})();
