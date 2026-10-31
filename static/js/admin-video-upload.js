(function () {
  document.querySelectorAll(".js-video-upload").forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var maxMb = parseInt(input.getAttribute("data-max-mb") || "1024", 10) || 1024;
      var maxBytes = maxMb * 1024 * 1024;
      if (file.size > maxBytes) {
        alert(
          "Файл «" +
            file.name +
            "» слишком большой (" +
            Math.round(file.size / (1024 * 1024)) +
            " МБ). Лимит сервера: " +
            maxMb +
            " МБ."
        );
        input.value = "";
      }
    });
  });
})();
