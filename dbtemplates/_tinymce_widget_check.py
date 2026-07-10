"""Out-of-process check of the ``SourceAwareAdminTinyMCE`` widget branch.

Run via subprocess by ``test_tinymce_widget.py`` with
``DJANGO_SETTINGS_MODULE=dbtemplates.test_settings_tinymce`` so the TinyMCE
editor path (selected at ``admin.py`` import time) is actually loaded. Exits 0
and prints ``OK`` on success; raises (non-zero exit) on the first failed check.
"""

import django

django.setup()

from dbtemplates.admin import SourceAwareAdminTinyMCE  # noqa: E402

widget = SourceAwareAdminTinyMCE()

config = widget.get_mce_config({"id": "id_content"})
plugins = config["plugins"]
plugin_tokens = plugins.split() if isinstance(plugins, str) else list(plugins)
# django-tinymce's default ``plugins`` is a comma-separated string.
flat = []
for tok in plugin_tokens:
    flat.extend(part for part in tok.split(",") if part)
assert "code" in flat, f"code plugin missing from {plugins!r}"
assert config["entity_encoding"] == "raw", config.get("entity_encoding")
assert config["verify_html"] is False, config.get("verify_html")
assert config["convert_urls"] is False, config.get("convert_urls")

# The protect snippet must be present AND loaded after TinyMCE's own core JS,
# so ``tinymce.overrideDefaults`` runs against a defined ``tinymce`` global.
js = [str(item) for item in widget.media._js]
protect = "dbtemplates/js/tinymce_django_protect.js"
assert protect in js, f"protect JS missing from media: {js}"
core_indices = [i for i, src in enumerate(js) if "tinymce" in src and src != protect]
assert core_indices, f"no TinyMCE core JS found in media: {js}"
assert js.index(protect) > min(core_indices), (
    f"protect JS must load after TinyMCE core: {js}"
)

# The widget must render without error and carry TinyMCE's config attribute.
html = widget.render("content", "", {"id": "id_content"})
assert "id_content" in html, "rendered widget missing the field id"
assert "mce" in html.lower(), "rendered widget does not look TinyMCE-enabled"

print("OK")
