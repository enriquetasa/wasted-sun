(function () {
  "use strict";

  function easeOutExpo(t) {
    return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
  }

  function parseTarget(el) {
    var raw = el.getAttribute("data-target");
    if (raw == null || raw === "") return NaN;
    return parseFloat(String(raw).replace(",", "."), 10);
  }

  function runCountUp(el, locale, duration, delay, onDone) {
    var target = parseTarget(el);
    var finalText = el.getAttribute("data-final") || "";
    var kind = el.getAttribute("data-kind") || "mwh";

    if (!Number.isFinite(target) || finalText === "") {
      if (typeof onDone === "function") onDone();
      return;
    }

    var start = performance.now() + delay;
    var fmtMwh = function (n) {
      return (
        new Intl.NumberFormat(locale, {
          minimumFractionDigits: 3,
          maximumFractionDigits: 3,
        }).format(n) + " MWh"
      );
    };
    var fmtEur = function (n) {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency: "EUR",
      }).format(n);
    };

    function frame(now) {
      if (now < start) {
        requestAnimationFrame(frame);
        return;
      }
      var t = Math.min(1, (now - start) / duration);
      var eased = easeOutExpo(t);
      var current = target * eased;
      if (kind === "eur") {
        el.textContent = fmtEur(current);
      } else {
        el.textContent = fmtMwh(current);
      }
      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        el.textContent = finalText;
        if (typeof onDone === "function") onDone();
      }
    }

    el.textContent = kind === "eur" ? fmtEur(0) : fmtMwh(0);
    requestAnimationFrame(frame);
  }

  function init() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var locale = document.documentElement.lang || "es";
    var nodes = document.querySelectorAll("[data-kpi-animate]");
    if (!nodes.length) return;

    if (reduce) {
      nodes.forEach(function (el) {
        var fin = el.getAttribute("data-final");
        if (fin) el.textContent = fin;
      });
      return;
    }

    if (!document.documentElement.classList.contains("js")) {
      nodes.forEach(function (el) {
        var fin = el.getAttribute("data-final");
        if (fin) el.textContent = fin;
      });
      return;
    }

    var duration = 1900;
    var stagger = 160;
    nodes.forEach(function (el, i) {
      runCountUp(el, locale, duration, i * stagger, null);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
