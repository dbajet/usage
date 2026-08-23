"use strict";

(function () {
  const saved = localStorage.getItem("theme");
  const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = saved || system;
})();

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = current;
  localStorage.setItem("theme", current);
}

addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("theme-btn");
  if (button) button.addEventListener("click", toggleTheme);
});
