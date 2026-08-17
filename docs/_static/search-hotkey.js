/* Focus Furo's sidebar search on Ctrl+K / Cmd+K */
document.addEventListener("keydown", function (e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    var input = document.querySelector(".sidebar-search");
    if (input) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  }
});
