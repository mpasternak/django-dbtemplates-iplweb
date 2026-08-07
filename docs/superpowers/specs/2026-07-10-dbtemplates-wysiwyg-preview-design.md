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
- **Feature B — PREVIEW:** a collapsed preview panel (label `_("Preview")`;
  Polish "Podgląd" via the locale catalog) on the change form that
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
- Replacing CodeMirror or Redactor support. They keep their current selection
  behaviour exactly as-is: CodeMirror **and** TinyMCE enabled together raises
  `ImproperlyConfigured`, while Redactor is simply superseded by TinyMCE through
  `elif` precedence (`admin.py`). This is not a true mutual-exclusivity
  guarantee for Redactor — just the existing behaviour, unchanged.
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
└─ Preview panel (Feature B, collapsed; labels via gettext)
    ├─ context <textarea> (JSON)
    ├─ [Detect] button ─────► POST admin: preview-detect/  ─► build_context_scaffold()
    ├─ [Render] button ─────► POST admin: preview-render/   ─► engines['django'].from_string().render()
    └─ result <iframe srcdoc sandbox="allow-scripts">
```

New/changed files:

- `dbtemplates/admin.py` — new widget subclass (A); custom admin URLs and views,
  `change_form_template`, and `Media` for the preview panel (B).
- `dbtemplates/conf.py` — new `DBTEMPLATES_TINYMCE_CONFIG` setting (A).
- `pyproject.toml` — add an optional extra `tinymce` pinning a minimum
  `django-tinymce` version (see Dependency floor below); the base package keeps
  no hard tinymce dependency.
- `dbtemplates/utils/introspect.py` — new module, `build_context_scaffold()` (B).
- `dbtemplates/templates/admin/dbtemplates/template/change_form.html` — override
  adding the preview panel (B).
- `dbtemplates/static/dbtemplates/js/preview.js` — panel wiring (B).
- `dbtemplates/static/dbtemplates/js/tinymce_django_protect.js` —
  `tinymce.overrideDefaults({protect: [...]})` snippet (A; see wrinkle below).
- `dbtemplates/static/dbtemplates/css/preview.css` — panel layout (B).
- `dbtemplates/locale/pl/LC_MESSAGES/django.po` — Polish strings for the new
  UI labels (A/B).
- Docs: README section describing the TinyMCE setup and the preview panel.

## Feature A — template-aware TinyMCE config

### Behaviour

When `DBTEMPLATES_USE_TINYMCE = True`, the `content` field uses
`SourceAwareAdminTinyMCE` (a subclass of `tinymce.widgets.AdminTinyMCE`).

**Where the merge happens.** django-tinymce already merges its own
`DEFAULT_CONFIG` (plus language keys) with the widget's `mce_attrs` inside
`TinyMCE.get_mce_config()`. To avoid double-applying `DEFAULT_CONFIG` and to be
able to *append* to (not replace) the project's plugin/toolbar values, the
subclass **overrides `get_mce_config()`**:

1. call `super().get_mce_config(...)` → the config already merged by
   django-tinymce (its `DEFAULT_CONFIG` + any project `mce_attrs`);
2. apply dbtemplates' template-aware overrides (below);
3. apply the new `DBTEMPLATES_TINYMCE_CONFIG` setting (a dict) on top, so the
   project controls styling/plugins/toolbar;
4. **last**, run the `code` plugin/button normalization (see rule below).

Ordering rationale: the `code` append runs **after** `DBTEMPLATES_TINYMCE_CONFIG`
so that a project setting its own `plugins`/`toolbar` in that setting cannot
accidentally drop the shipped source-view button. The deliberate opt-out is
`toolbar: false` (or an absent toolbar), which the normalization rule leaves
untouched. Thus: source view is guaranteed unless the project explicitly
disables the toolbar.

The JSON-serializable keys flow through this merged config. `protect` is handled
separately (see wrinkle below) because it cannot be JSON-serialized.

### dbtemplates template-aware defaults

- `entity_encoding: 'raw'` — do not HTML-encode entities.
- `verify_html: false` — do not drop "unknown" markup.
- `convert_urls: false` — do not rewrite `href`/`src`, so `{% url %}` / `{{ }}`
  inside attributes survives TinyMCE's URL converter.
- `code` plugin + toolbar button (via the normalization rule).
- `protect`: regexes for `{{ … }}`, `{% … %}`, `{# … #}` (injected via JS).

### `code` plugin/toolbar normalization

`plugins` may be a comma/space-separated **string** or a **list**; `toolbar` may
be a string, a list of strings, `false`, or absent. The append logic must handle
each:

- **`plugins`:** if it already contains `code`, leave it; if a string, append
  `" code"`; if a list, append `"code"`.
- **`toolbar`:** if it already contains `code`, leave it; if a **string** or
  **list**, append a `code` entry; if `false` or **absent**, leave it as-is —
  never resurrect a deliberately-disabled toolbar. Note: django-tinymce's
  `DEFAULT_CONFIG` defines a `toolbar` string and `menubar: False`, so under
  defaults the toolbar button is the only access path and this rule adds it
  correctly. If a project disables the toolbar entirely, the source view is
  unavailable — documented, not worked around.

### Implementation wrinkle: `protect` regexes

`protect` values are JavaScript `RegExp` objects. django-tinymce serializes the
config to JSON (`json.dumps(..., cls=DjangoJSONEncoder)` into `data-mce-conf`,
`JSON.parse`d by `init_tinymce.js`), so regexes cannot pass through `mce_attrs`.
Note also that `protect` is applied in a `BeforeSetContent` handler, so it must
be registered **before** the editor's initial `setContent`. Passing it through a
per-editor `setup` string would fire early enough but is clobber-prone (a
project's own `setup` would replace it); an `init_instance_callback` fires too
late. Either way, a `RegExp` array is not JSON-serializable, so it cannot ride
`mce_attrs` at all.

Resolution: a static JS file (`tinymce_django_protect.js`) added to the widget's
`Media` **after** django-tinymce's own JS, calling
`tinymce.overrideDefaults({ protect: [/\{\{[\s\S]*?\}\}/g, /\{%[\s\S]*?%\}/g,
/\{#[\s\S]*?#\}/g] })`. `overrideDefaults` shallow-merges global init defaults
before any editor initializes (per-editor `init` still wins per key, and our
merged config never sets `protect`), sidestepping both the JSON and init-order
problems. Two ordering caveats to document: (a) the `Media` entry must load
after `tinymce.min.js`/django-tinymce assets; (b) `overrideDefaults` is
last-call-wins — a host project that calls `tinymce.overrideDefaults` in its own
admin JS would wipe these regexes, so the README notes it.

### Dependency floor

The design leans on two django-tinymce facts: the internal `get_mce_config()`
override point (present since django-tinymce 3.4.0) and a bundled TinyMCE that
ships `overrideDefaults`/`protect`/`convert_urls` (TinyMCE 7.x). Phase 1 pins a
minimum `django-tinymce` version in a new optional extra
(`pip install django-dbtemplates[tinymce]`) and documents it in the README.
`configure_use_tinymce` continues to only check `INSTALLED_APPS`; the version
floor is expressed through packaging, not a runtime assertion, to avoid coupling
import-time behaviour to a private API.

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
   scope and attach **exactly 2** sample elements (copies of the collected
   element shape) to the corresponding list.
3. For each VAR token (`a.b.c|filter`): drop filters (split on `|`, keep the
   head), split the variable path on `.`. If the first segment is an active loop
   variable, record the remaining path into that loop's element shape; otherwise
   record it into the top-level context.
4. Build nested dicts from dotted paths. Leaf value heuristic:
   - segment name is `id` or `pk`, or ends with `_id` → integer **`1`**,
   - otherwise → a string equal to the variable path (a readable placeholder).
5. Numeric literals and non-variable expressions (e.g. loop over a literal) are
   ignored.
6. Return the assembled dict.

**Determinism / conflict rules (v1):**

- A name that appears both as a scalar (`{{ user }}`) and as a dotted parent
  (`{{ user.name }}`) resolves to the **dict** form (`{"user": {"name": …}}`);
  the parent-of-attributes reading wins.
- `{% for k, v in items %}` (multiple loop targets) and the `reversed` suffix
  are **not** modelled in v1: `items` still becomes a 2-element list, but the
  loop targets `k`/`v` are treated as opaque (their attribute accesses are
  dropped rather than mis-attributed). Documented, not worked around.
- Sample values are fixed constants (no randomness), so output is fully
  deterministic and unit-testable.
- **Bare loop variable** (`{{ item }}` with no attribute access) → list elements
  are strings equal to the loop-variable name (not empty dicts).
- **`forloop.*`** (`forloop.counter`, `forloop.first`, …) is a Django-provided
  loop helper, not user context: it is explicitly ignored (no top-level
  `forloop` key emitted).
- **Unterminated `{% for %}`** (missing `{% endfor %}`): flush open scopes at
  end-of-input, attaching whatever element shape was collected.
- **List-vs-dict collision** (`{% for x in things %}` and `{{ things.count }}`):
  the loop registration wins — `things` stays a list; a stray attribute access on
  the same name is dropped (documented, not merged).

Scope boundaries for v1 (per decision 5): no filter-based type inference, no
`{% with %}` handling, no `{% include %}` variable resolution, no attempt to
satisfy `{% if %}` conditions. Nested loops are handled to the extent that the
scope stack naturally supports them; deeper correctness is not guaranteed and
the user edits the JSON as needed.

**API stability note:** `django.template.base.Lexer` is an internal, undocumented
API (stable in practice). Tests pin the import and assert the tokenizer contract
(`TokenType.{TEXT,VAR,BLOCK,COMMENT}`) so a Django upgrade that changes it fails
loudly rather than silently.

### Admin endpoints

`TemplateAdmin.get_urls()` prepends two named URLs, both requiring
`self.has_change_permission(request)` (staff + change perm) and accepting POST:

- **`preview-detect/`** — body: `content`. Returns `{"context": <pretty JSON
  string>}` produced by `build_context_scaffold`.
- **`preview-render/`** — body: `content`, `context` (JSON string). Parses the
  context with `json.loads`, renders via
  `engines['django'].from_string(content).render(context_dict)`, and returns
  `{"html": <rendered>}`. On any exception (invalid JSON, unknown tag, template
  syntax error, render error), returns `{"error": <readable message>}` with
  HTTP **400**; the panel shows the error text instead of a result.

Both views are wrapped with `self.admin_site.admin_view(...)` (staff auth +
CSRF), and additionally check `self.has_change_permission(request)`, returning
403 otherwise. They accept POST only and return `JsonResponse`.

Notes:

- `has_change_permission` gates the endpoints, so a user with add-only rights
  does not get preview on the *add* form. Accepted as a v1 decision.
- `engines['django']` requires a `DjangoTemplates` backend in `TEMPLATES` (which
  dbtemplates' loader needs anyway). If absent, the blanket `except` reports a
  readable error rather than a 500.

### Change-form UI

- `TemplateAdmin.change_form_template` points at
  `admin/dbtemplates/template/change_form.html`, which extends the default admin
  change form and injects a collapsed preview panel (`_("Preview")`) below the
  content field.
- The panel contains: a JSON `<textarea>` for the context, a "Detect" and a
  "Render" button, and an `<iframe srcdoc sandbox="allow-scripts">` for the
  rendered output. The `sandbox` attribute (with `allow-scripts` but **without**
  `allow-same-origin`) gives the frame an opaque origin, so a rendered template
  cannot reach `parent.document` or act with the staff session — this isolates
  both CSS *and* JS, not just CSS.
- All user-facing labels use `gettext` with English msgids
  (`_("Preview")`, `_("Detect")`, `_("Render")`, …); Polish is supplied via the
  existing `locale/pl` catalog, matching the package's translation convention.
- `preview.js` (added via the admin `Media`) wires the buttons:
  - reads the current editor content from TinyMCE
    (`tinymce.get(<id>).getContent()`) when active, else from the textarea;
  - sends the `X-CSRFToken` header on every POST, reading the token from the
    change form's hidden `csrfmiddlewaretoken` input (robust under
    `CSRF_COOKIE_HTTPONLY` / `CSRF_USE_SESSIONS`, unlike a cookie read);
  - "Detect" POSTs `content` to `preview-detect/` and fills the JSON textarea;
  - "Render" POSTs `content` + `context` to `preview-render/` and sets the
    iframe `srcdoc` to the returned HTML, or shows the returned error.
- URLs for the endpoints are exposed to JS via the change_form template (data
  attributes) so no hard-coded admin path is assumed.
- Static assets ship as standard app static files under
  `static/dbtemplates/{js,css}` (already covered by `pyproject.toml` package
  data), referenced from the admin `Media` — not via `DBTEMPLATES_MEDIA_PREFIX`
  (which is CodeMirror-specific legacy).

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
    list of exactly 2 dicts each with a `title` key;
  - scalar/dict collision (`{{ user }}` + `{{ user.name }}`) → dict wins;
  - bare loop var `{% for x in xs %}{{ x }}{% endfor %}` → list of 2 strings;
  - `{{ forloop.counter }}` produces no top-level `forloop` key;
  - unterminated `{% for %}` (no `endfor`) flushes without raising;
  - list-vs-dict collision keeps `things` a list;
  - a template with `{% load unknown %}` does not raise and still yields the
    other variables.
- **Integration — endpoints:**
  - `preview-render/` returns rendered HTML for a valid template + context;
  - `preview-render/` returns a graceful `error` with HTTP 400 (not a 500
    traceback) for an unknown tag / invalid context JSON;
  - `preview-detect/` returns a JSON scaffold for posted content;
  - GET (non-POST) returns 405;
  - both endpoints reject non-staff / missing-permission requests (403);
  - a POST without a valid CSRF token is rejected (403).
- **Change form:**
  - the rendered add/change form's preview iframe carries
    `sandbox="allow-scripts"` (and not `allow-same-origin`).
- **Widget config:**
  - the effective TinyMCE config includes `code` in `plugins` and `toolbar`
    (verified for both string and list forms of those keys);
  - `code` is not duplicated when the project config already contains it;
  - a `toolbar: false` / absent toolbar is left untouched (not resurrected);
  - `entity_encoding`, `verify_html`, `convert_urls` are set as specified;
  - `DBTEMPLATES_TINYMCE_CONFIG` overrides merge on top of the defaults (has the
    last word).
- **Tag protection (config assertion):** the effective config sets
  `convert_urls: false`; the `protect` regexes cannot be asserted server-side
  (they live in the JS `overrideDefaults` file), so actual survival of
  `{% url %}`/`{{ var }}` inside `href` is a documented manual/browser check, not
  an automated test.

## Phasing

- **Phase 1 (Feature A):** `SourceAwareAdminTinyMCE`,
  `DBTEMPLATES_TINYMCE_CONFIG` setting, `protect` JS snippet, config-merge tests,
  README/docs. Independently shippable.
- **Phase 2 (Feature B):** `introspect.py` + unit tests, the two admin endpoints
  + integration tests, the change_form override + `preview.js` + `preview.css`,
  docs.

## Open questions / risks

- `protect` regex injection uses `tinymce.overrideDefaults` (confirmed present in
  the bundled TinyMCE 7.8). Risk is limited to `Media` load-order; the snippet
  must load after django-tinymce's core JS. Verified during Phase 1.
- Full render executes template logic against the real environment. This grants
  no new privilege (staff who edit templates already have equivalent
  capability), and the rendered output is confined to a
  `sandbox="allow-scripts"` iframe (opaque origin), so it cannot act with the
  admin session.
- `build_context_scaffold` relies on the internal `django.template.base.Lexer`;
  a contract test guards against silent breakage on Django upgrades.
