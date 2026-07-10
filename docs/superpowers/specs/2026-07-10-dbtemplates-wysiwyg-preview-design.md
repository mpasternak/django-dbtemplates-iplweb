# dbtemplates: WYSIWYG editor with source view and rendered PREVIEW

- **Date:** 2026-07-10
- **Status:** Approved (brainstorming), pending implementation
- **Scope:** Admin editing experience for the `Template` model

## Summary

Add a richer editing experience to the dbtemplates admin change form, delivered
in two phases behind a single coherent design:

- **Feature A — WYSIWYG + source view:** ship an opinionated, template-aware
  TinyMCE configuration out of the box. It enables TinyMCE's built-in `code`
  plugin (a toolbar button that opens a modal with the raw source) and protects
  Django template tags (`{% %}`, `{{ }}`, `{# #}`) from being mangled by the
  HTML cleaner.
- **Feature B — PREVIEW:** a collapsed "Podgląd" panel on the change form that
  lets an editor (1) auto-detect a best-effort context scaffold from the
  template source, (2) edit that context as JSON, and (3) render the template
  with that context, showing the result in an isolated iframe next to the
  source.

Both features are staff-only (they live in the Django admin). Feature B is
logically independent of Feature A but reads the current editor content from
whichever widget is active (TinyMCE or a plain textarea).

## Goals

- Give editors a WYSIWYG editor for the (mostly HTML) templates stored in the
  database, without silently corrupting embedded Django template syntax.
- Always provide an escape hatch to view and edit the raw source.
- Let editors preview a template's rendered output with a plausible,
  auto-scaffolded context, iterating without leaving the change form.

## Non-goals

- Perfect static analysis of arbitrary Django templates. Context detection is
  explicitly best-effort and always hand-editable.
- A general-purpose CMS or template gallery.
- Replacing CodeMirror or Redactor support (they remain as-is and mutually
  exclusive with TinyMCE, as today).
- Changing the storage model (`Template.content` stays a single `TextField`).

## Decisions (from brainstorming)

1. Content is **mostly HTML** with light `{{ variable }}` interpolation (email
   bodies, flatpages, CMS blocks). WYSIWYG is appropriate; Django tags only need
   protection, not full parsing.
2. Source view uses **TinyMCE's built-in `code` plugin** (a toolbar button
   opening a modal), not a custom dual-tab widget. Zero custom JS for the
   source view itself.
3. dbtemplates ships a **ready-to-use, template-aware TinyMCE config out of the
   box**, merged with the project's `TINYMCE_DEFAULT_CONFIG`, overridable via a
   new setting.
4. The two features are one spec, **phased implementation**: Feature A first,
   then Feature B.
5. Context auto-detection is the **core heuristic only** (variables, attribute
   access, for-loops, `id`/`pk` → integer, else string). No filter-based type
   inference, no nested-scope resolution in v1.
6. Rendering is a **full render + graceful errors**: use the normal Django
   engine so `extends`/`include`/`load` resolve as in production; catch any
   exception and show a readable error instead of the result.
7. The preview UI is an **inline split panel on the change form**, **collapsed
   by default**.

## Architecture overview

```
Django admin change form (TemplateAdmin)
├─ content field
│   └─ widget: SourceAwareAdminTinyMCE  (Feature A)  — code plugin + tag protection
└─ "Podgląd" panel (Feature B, collapsed)
    ├─ context <textarea> (JSON)
    ├─ [Wykryj] button ─────► POST admin: preview-detect/  ─► build_context_scaffold()
    ├─ [Renderuj] button ───► POST admin: preview-render/   ─► engines['django'].from_string().render()
    └─ result <iframe srcdoc>
```

New/changed files:

- `dbtemplates/admin.py` — new widget subclass (A); custom admin URLs and views,
  `change_form_template`, and `Media` for the preview panel (B).
- `dbtemplates/conf.py` — new `DBTEMPLATES_TINYMCE_CONFIG` setting (A).
- `dbtemplates/utils/introspect.py` — new module, `build_context_scaffold()` (B).
- `dbtemplates/templates/admin/dbtemplates/template/change_form.html` — override
  adding the preview panel (B).
- `dbtemplates/static/dbtemplates/js/preview.js` — panel wiring (B).
- `dbtemplates/static/dbtemplates/js/tinymce_django_protect.js` — TinyMCE init
  snippet injecting the `protect` regexes (A; see wrinkle below).
- `dbtemplates/static/dbtemplates/css/preview.css` — panel layout (B).
- Docs: README section describing the TinyMCE setup and the preview panel.

## Feature A — template-aware TinyMCE config

### Behaviour

When `DBTEMPLATES_USE_TINYMCE = True`, the `content` field uses
`SourceAwareAdminTinyMCE` (a subclass of `tinymce.widgets.AdminTinyMCE`) whose
effective config is built by merging, in order:

1. the project's `TINYMCE_DEFAULT_CONFIG` (django-tinymce's baseline),
2. dbtemplates' template-aware defaults (below),
3. any keys from the new `DBTEMPLATES_TINYMCE_CONFIG` setting (project override).

The `code` entry is **appended** to `plugins` and to `toolbar` if not already
present (never replacing the project's plugin/toolbar list wholesale).

### dbtemplates template-aware defaults

- `plugins`: ensure `code` is included.
- `toolbar`: ensure a `code` button is present.
- `entity_encoding: 'raw'` — do not HTML-encode entities.
- `verify_html: false` — do not drop "unknown" markup.
- `protect`: regexes for `{{ … }}`, `{% … %}`, `{# … #}` so TinyMCE leaves
  Django template syntax untouched.

### Implementation wrinkle: `protect` regexes

`protect` values are JavaScript `RegExp` objects. django-tinymce serializes the
config dict to JSON, and regexes are not JSON-serializable. Therefore the
`protect` array cannot be passed through `mce_attrs`.

Resolution: inject the `protect` regexes via a small static JS init snippet
(`tinymce_django_protect.js`) added to the widget's `Media`, which sets them on
the TinyMCE init options (e.g. via a `setup`/`init_instance_callback` hook or by
extending the config object before init). The JSON-serializable keys
(`entity_encoding`, `verify_html`, `plugins`, `toolbar`) still flow through
`mce_attrs`/the merged config. The spec accepts one small JS file as the cost of
correct tag protection.

### Backward compatibility

- Projects already using `DBTEMPLATES_USE_TINYMCE` gain the `code` button and
  tag protection automatically. This is a strict improvement (previously a naive
  config would mangle templates), accepted per decision 3; no separate opt-in
  flag is introduced.
- The existing `ImproperlyConfigured` guard (CodeMirror **and** TinyMCE enabled
  simultaneously) is retained unchanged.

## Feature B — PREVIEW

### Context introspection (`build_context_scaffold`)

`dbtemplates/utils/introspect.py` exposes:

```python
def build_context_scaffold(content: str) -> dict:
    """Best-effort context scaffold for a Django template string.

    Never raises: unrecognised constructs are skipped. The result is intended
    to be serialised to JSON and hand-edited by the user.
    """
```

**Key technical decision:** analysis uses Django's **tokenizer**
(`django.template.base.Lexer`), not template compilation. Compiling a template
that contains `{% load unknown %}` or unknown custom tags raises; tokenizing
never does — it only splits the source into TEXT / VAR / BLOCK / COMMENT tokens.
This keeps introspection robust against templates the current environment cannot
fully compile.

Algorithm:

1. Tokenize `content` with `Lexer`.
2. Maintain a stack of active `for`-loop scopes. On a `for x in <seq>` block,
   record `<seq>` (the resolved variable path, ignoring filters) as a list and
   push loop variable `x` with an empty element shape. On `endfor`, pop the
   scope and attach 2–3 sample elements (copies of the collected element shape)
   to the corresponding list.
3. For each VAR token (`a.b.c|filter`): drop filters (split on `|`, keep the
   head), split the variable path on `.`. If the first segment is an active loop
   variable, record the remaining path into that loop's element shape; otherwise
   record it into the top-level context.
4. Build nested dicts from dotted paths. Leaf value heuristic:
   - segment name is `id` or `pk`, or ends with `_id` → integer (a small,
     deterministic sample number),
   - otherwise → a string equal to the variable path (a readable placeholder).
5. Numeric literals and non-variable expressions (e.g. loop over a literal) are
   ignored.
6. Return the assembled dict.

Scope boundaries for v1 (per decision 5): no filter-based type inference, no
`{% with %}` handling, no `{% include %}` variable resolution, no attempt to
satisfy `{% if %}` conditions. Nested loops are handled to the extent that the
scope stack naturally supports them; deeper correctness is not guaranteed and
the user edits the JSON as needed.

### Admin endpoints

`TemplateAdmin.get_urls()` prepends two named URLs, both requiring
`self.has_change_permission(request)` (staff + change perm) and accepting POST:

- **`preview-detect/`** — body: `content`. Returns `{"context": <pretty JSON
  string>}` produced by `build_context_scaffold`.
- **`preview-render/`** — body: `content`, `context` (JSON string). Parses the
  context with `json.loads`, renders via
  `engines['django'].from_string(content).render(context_dict)`, and returns
  `{"html": <rendered>}`. On any exception (invalid JSON, unknown tag, template
  syntax error, render error), returns `{"error": <readable message>}` with an
  appropriate status; the panel shows the error text instead of a result.

Both are standard admin views (CSRF-protected, wired through `admin_view` where
appropriate) returning `JsonResponse`.

### Change-form UI

- `TemplateAdmin.change_form_template` points at
  `admin/dbtemplates/template/change_form.html`, which extends the default admin
  change form and injects a collapsed "Podgląd" panel below the content field.
- The panel contains: a JSON `<textarea>` for the context, `[Wykryj]` and
  `[Renderuj]` buttons, and an `<iframe srcdoc>` for the rendered output. The
  iframe isolates the rendered template's CSS/JS from the admin styles.
- `preview.js` (added via the admin `Media`) wires the buttons:
  - reads the current editor content from TinyMCE
    (`tinymce.get(<id>).getContent()`) when active, else from the textarea;
  - `[Wykryj]` POSTs `content` to `preview-detect/` and fills the JSON textarea;
  - `[Renderuj]` POSTs `content` + `context` to `preview-render/` and sets the
    iframe `srcdoc` to the returned HTML, or shows the returned error.
- URLs for the endpoints are exposed to JS via the change_form template (data
  attributes) so no hard-coded admin path is assumed.

## Error handling

- **Introspection** never raises; unrecognised constructs are skipped and the
  context is always hand-editable.
- **Render** catches every exception (bad context JSON, unknown `{% load %}`,
  template syntax error, missing variable behaviour) and returns a readable
  error string; the change form never breaks.
- **TinyMCE config** retains the existing `ImproperlyConfigured` guard when both
  CodeMirror and TinyMCE are enabled.

## Testing (TDD)

- **Unit — `build_context_scaffold`:**
  - plain variable `{{ title }}` → `{"title": "title"}`;
  - attribute access `{{ user.name }}` → `{"user": {"name": "user.name"}}`;
  - `id`/`pk`/`*_id` → integer;
  - filters stripped (`{{ user.name|upper }}` behaves like `{{ user.name }}`);
  - for-loop `{% for item in items %}{{ item.title }}{% endfor %}` → `items` is a
    list of 2–3 dicts each with a `title` key;
  - a template with `{% load unknown %}` does not raise and still yields the
    other variables.
- **Integration — endpoints:**
  - `preview-render/` returns rendered HTML for a valid template + context;
  - `preview-render/` returns a graceful `error` (not a 500 traceback) for an
    unknown tag / invalid context JSON;
  - `preview-detect/` returns a JSON scaffold for posted content;
  - both endpoints reject non-staff / missing-permission requests.
- **Widget config:**
  - the effective TinyMCE config includes `code` in `plugins` and `toolbar`;
  - `entity_encoding`, `verify_html` are set as specified;
  - `DBTEMPLATES_TINYMCE_CONFIG` overrides merge on top of the defaults.

## Phasing

- **Phase 1 (Feature A):** `SourceAwareAdminTinyMCE`,
  `DBTEMPLATES_TINYMCE_CONFIG` setting, `protect` JS snippet, config-merge tests,
  README/docs. Independently shippable.
- **Phase 2 (Feature B):** `introspect.py` + unit tests, the two admin endpoints
  + integration tests, the change_form override + `preview.js` + `preview.css`,
  docs.

## Open questions / risks

- `protect` regex injection depends on the exact TinyMCE init flow django-tinymce
  exposes; the JS snippet approach may need adjustment to the installed
  django-tinymce version. Verified during Phase 1.
- Full render executes template logic against the real environment; this is
  acceptable because staff who edit templates already have equivalent
  capability. No new privilege is granted.
