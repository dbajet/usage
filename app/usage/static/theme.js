"use strict";

(function () {
  const saved = localStorage.getItem("theme");
  const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = saved || system;
  // Phone or not, decided by the device rather than the window width: some
  // layouts (the sensor tiles) follow the device, so a narrow laptop window
  // keeps the desktop look and a phone held sideways keeps the compact one.
  const hints = navigator.userAgentData;
  const agent = navigator.userAgent;
  const isTablet = /iPad|Tablet/i.test(agent);
  const isPhone = !isTablet && (hints && typeof hints.mobile === "boolean"
    ? hints.mobile
    : /Android.*Mobile|iPhone|iPod|Windows Phone|Mobi/i.test(agent));
  document.documentElement.classList.toggle("device-mobile", Boolean(isPhone));
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
