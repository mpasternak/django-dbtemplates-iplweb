/* dbtemplates admin preview panel.
 *
 * Reads the current template source (from TinyMCE if active, else the plain
 * textarea), asks the admin endpoints to auto-detect a context scaffold and to
 * render the template, and shows the result in a sandboxed iframe.
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  ready(function () {
    var panel = document.getElementById("dbtemplates-preview");
    if (!panel) {
      return;
    }

    var detectUrl = panel.dataset.detectUrl;
    var renderUrl = panel.dataset.renderUrl;
    var fieldId = panel.dataset.contentField || "id_content";

    var contextArea = document.getElementById("dbtemplates-preview-context");
    var detectBtn = document.getElementById("dbtemplates-preview-detect");
    var renderBtn = document.getElementById("dbtemplates-preview-render");
    var errorBox = document.getElementById("dbtemplates-preview-error");
    var resultFrame = document.getElementById("dbtemplates-preview-result");

    function getContent() {
      if (window.tinymce && window.tinymce.get && window.tinymce.get(fieldId)) {
        return window.tinymce.get(fieldId).getContent();
      }
      var field = document.getElementById(fieldId);
      return field ? field.value : "";
    }

    function getCsrfToken() {
      var input = document.querySelector("input[name=csrfmiddlewaretoken]");
      return input ? input.value : "";
    }

    function showError(message) {
      if (!errorBox) {
        return;
      }
      errorBox.textContent = message;
      errorBox.hidden = false;
    }

    function clearError() {
      if (errorBox) {
        errorBox.textContent = "";
        errorBox.hidden = true;
      }
    }

    function post(url, data) {
      var body = new URLSearchParams(data);
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: body.toString(),
      });
    }

    function handleJson(response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    }

    if (detectBtn) {
      detectBtn.addEventListener("click", function () {
        clearError();
        post(detectUrl, { content: getContent() })
          .then(handleJson)
          .then(function (res) {
            if (res.ok && typeof res.data.context === "string") {
              contextArea.value = res.data.context;
            } else {
              showError(res.data.error || "Detection failed.");
            }
          })
          .catch(function (err) {
            showError(String(err));
          });
      });
    }

    if (renderBtn) {
      renderBtn.addEventListener("click", function () {
        clearError();
        post(renderUrl, {
          content: getContent(),
          context: contextArea ? contextArea.value : "{}",
        })
          .then(handleJson)
          .then(function (res) {
            if (res.ok && typeof res.data.html === "string") {
              resultFrame.srcdoc = res.data.html;
            } else {
              resultFrame.srcdoc = "";
              showError(res.data.error || "Render failed.");
            }
          })
          .catch(function (err) {
            showError(String(err));
          });
      });
    }
  });
})();
