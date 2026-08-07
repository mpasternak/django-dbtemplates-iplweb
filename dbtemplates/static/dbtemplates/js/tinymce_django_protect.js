// dbtemplates: protect Django template tags from TinyMCE's HTML cleaner.
//
// Registers `protect` regexes globally via tinymce.overrideDefaults so that
// `{{ ... }}`, `{% ... %}` and `{# ... #}` survive editing. This runs before
// any editor initializes; a per-editor `init` key still wins, and the config
// dbtemplates ships never sets `protect`, so these defaults apply.
//
// NOTE: overrideDefaults is last-call-wins. A host project that calls
// tinymce.overrideDefaults itself in its own admin JS would clobber these
// regexes (see README).
(function () {
  if (typeof tinymce !== "undefined" && tinymce.overrideDefaults) {
    tinymce.overrideDefaults({
      protect: [
        /\{\{[\s\S]*?\}\}/g,
        /\{%[\s\S]*?%\}/g,
        /\{#[\s\S]*?#\}/g,
      ],
    });
  }
})();
