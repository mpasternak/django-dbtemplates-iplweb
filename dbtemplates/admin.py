import json
import posixpath
import re
from django import forms
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.http import (
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.template import engines
from django.urls import path
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django.utils.safestring import mark_safe

from dbtemplates.conf import settings
from dbtemplates.models import Template, add_template_to_cache, remove_cached_template
from dbtemplates.utils.introspect import build_context_scaffold
from dbtemplates.utils.template import check_template_syntax

# Check if either django-reversion-compare or django-reversion is installed and
# use reversion_compare's CompareVersionAdmin or reversion's VersionAdmin as
# the base admin class if yes
if settings.DBTEMPLATES_USE_REVERSION_COMPARE:
    from reversion_compare.admin import CompareVersionAdmin \
        as TemplateModelAdmin
elif settings.DBTEMPLATES_USE_REVERSION:
    from reversion.admin import VersionAdmin as TemplateModelAdmin
else:
    from django.contrib.admin import ModelAdmin as TemplateModelAdmin  # noqa


def _tokenize_tinymce_list(value):
    """Split a TinyMCE plugins/toolbar string into tokens.

    TinyMCE accepts both comma- and space-separated lists (django-tinymce's
    default ``plugins`` is comma-separated, e.g. ``"advlist,autolink,code"``),
    so we split on commas, whitespace and the ``|`` toolbar-group separator.
    """
    return [tok for tok in re.split(r"[,\s|]+", value) if tok]


def _add_code_to_plugins(plugins):
    """Return ``plugins`` with the ``code`` plugin appended if absent.

    ``plugins`` may be a comma/space-separated string or a list of strings.
    """
    if plugins is None:
        return "code"
    if isinstance(plugins, str):
        if "code" in _tokenize_tinymce_list(plugins):
            return plugins
        return f"{plugins} code" if plugins else "code"
    if isinstance(plugins, (list, tuple)):
        if "code" in plugins:
            return plugins
        return list(plugins) + ["code"]
    return plugins


def _add_code_to_toolbar(toolbar):
    """Return ``toolbar`` with a ``code`` button appended if appropriate.

    A ``toolbar`` that is ``False`` or absent is left untouched: a disabled
    toolbar is a deliberate opt-out and must never be resurrected.
    """
    if toolbar is None or toolbar is False:
        return toolbar
    if isinstance(toolbar, str):
        if "code" in _tokenize_tinymce_list(toolbar):
            return toolbar
        return f"{toolbar} code" if toolbar else "code"
    if isinstance(toolbar, (list, tuple)):
        # toolbar as a list is a list of toolbar-group strings; treat "code"
        # as a group entry.
        if any("code" in _tokenize_tinymce_list(str(group)) for group in toolbar):
            return toolbar
        return list(toolbar) + ["code"]
    return toolbar


def apply_template_tinymce_config(config):
    """Return a new TinyMCE config dict with dbtemplates' template-aware tweaks.

    Takes an already-merged TinyMCE config (as produced by django-tinymce's
    ``get_mce_config``) and returns a new dict where:

    1. dbtemplates' overrides are applied (``entity_encoding='raw'``,
       ``verify_html=False``, ``convert_urls=False``);
    2. the project's ``DBTEMPLATES_TINYMCE_CONFIG`` setting is merged on top
       (it has the last word over styling/plugins/toolbar);
    3. **last**, the ``code`` source-view plugin/button is normalized into
       ``plugins`` and ``toolbar`` so a project config cannot accidentally
       drop the source-view button. A ``toolbar: False``/absent toolbar is the
       deliberate opt-out and is left untouched.

    ``protect`` is intentionally *not* handled here: those values are JS
    ``RegExp`` objects, are not JSON-serializable, and are injected via a
    separate static JS file (``tinymce_django_protect.js``).
    """
    result = dict(config)
    result["entity_encoding"] = "raw"
    result["verify_html"] = False
    result["convert_urls"] = False
    result.update(settings.DBTEMPLATES_TINYMCE_CONFIG)
    # Run the code normalization LAST, after DBTEMPLATES_TINYMCE_CONFIG, so a
    # project's own plugins/toolbar cannot drop the source button.
    result["plugins"] = _add_code_to_plugins(result.get("plugins"))
    if "toolbar" in result:
        result["toolbar"] = _add_code_to_toolbar(result["toolbar"])
    return result


class CodeMirrorTextArea(forms.Textarea):

    """
    A custom widget for the CodeMirror browser editor to be used with the
    content field of the Template model.
    """
    class Media:
        css = dict(screen=[posixpath.join(
            settings.DBTEMPLATES_MEDIA_PREFIX, 'css/editor.css')])
        js = [posixpath.join(settings.DBTEMPLATES_MEDIA_PREFIX,
                             'js/codemirror.js')]

    def render(self, name, value, attrs=None, renderer=None):
        result = []
        result.append(
            super().render(name, value, attrs))
        result.append("""
<script type="text/javascript">
  var editor = CodeMirror.fromTextArea('id_%(name)s', {
    path: "%(media_prefix)sjs/",
    parserfile: "parsedjango.js",
    stylesheet: "%(media_prefix)scss/django.css",
    continuousScanning: 500,
    height: "40.2em",
    tabMode: "shift",
    indentUnit: 4,
    lineNumbers: true
  });
</script>
""" % dict(media_prefix=settings.DBTEMPLATES_MEDIA_PREFIX, name=name))
        return mark_safe("".join(result))


if settings.DBTEMPLATES_USE_CODEMIRROR:
    TemplateContentTextArea = CodeMirrorTextArea
else:
    TemplateContentTextArea = forms.Textarea

if settings.DBTEMPLATES_AUTO_POPULATE_CONTENT:
    content_help_text = _("Leaving this empty causes Django to look for a "
                          "template with the given name and populate this "
                          "field with its content.")
else:
    content_help_text = ""

if settings.DBTEMPLATES_USE_CODEMIRROR and settings.DBTEMPLATES_USE_TINYMCE:
    raise ImproperlyConfigured("You may use either CodeMirror or TinyMCE "
                               "with dbtemplates, not both. Please disable "
                               "one of them.")

if settings.DBTEMPLATES_USE_TINYMCE:
    from tinymce.widgets import AdminTinyMCE

    class SourceAwareAdminTinyMCE(AdminTinyMCE):
        """AdminTinyMCE that ships the ``code`` source view and Django-tag
        protection out of the box.

        ``get_mce_config`` layers dbtemplates' template-aware overrides,
        ``DBTEMPLATES_TINYMCE_CONFIG``, and the ``code`` plugin/button on top
        of django-tinymce's merged config. The tag-protection ``protect``
        regexes are injected via a static JS file (added to ``Media`` after
        django-tinymce's own JS) because they cannot be JSON-serialized.
        """

        def get_mce_config(self, attrs):
            config = super().get_mce_config(attrs)
            return apply_template_tinymce_config(config)

        @property
        def media(self):
            return super().media + forms.Media(
                js=["dbtemplates/js/tinymce_django_protect.js"]
            )

    TemplateContentTextArea = SourceAwareAdminTinyMCE
elif settings.DBTEMPLATES_USE_REDACTOR:
    from redactor.widgets import RedactorEditor
    TemplateContentTextArea = RedactorEditor


class TemplateAdminForm(forms.ModelForm):

    """
    Custom AdminForm to make the content textarea wider.
    """
    content = forms.CharField(
        widget=TemplateContentTextArea(attrs={'rows': '24'}),
        help_text=content_help_text, required=False)

    class Meta:
        model = Template
        fields = ('name', 'content', 'sites', 'creation_date', 'last_changed')
        fields = "__all__"


class TemplateAdmin(TemplateModelAdmin):
    form = TemplateAdminForm
    change_form_template = "admin/dbtemplates/template/change_form.html"

    class Media:
        css = {"all": ["dbtemplates/css/preview.css"]}
        js = ["dbtemplates/js/preview.js"]

    readonly_fields = ['creation_date', 'last_changed']
    fieldsets = (
        (None, {
            'fields': ('name', 'content'),
            'classes': ('monospace',),
        }),
        (_('Advanced'), {
            'fields': (('sites'),),
        }),
        (_('Date/time'), {
            'fields': (('creation_date', 'last_changed'),),
            'classes': ('collapse',),
        }),
    )
    filter_horizontal = ('sites',)
    list_display = ('name', 'creation_date', 'last_changed', 'site_list')
    list_filter = ('sites',)
    save_as = True
    search_fields = ('name', 'content')
    actions = ['invalidate_cache', 'repopulate_cache', 'check_syntax']

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        preview_urls = [
            path(
                "preview-detect/",
                self.admin_site.admin_view(self.preview_detect_view),
                name="%s_%s_preview_detect" % info,
            ),
            path(
                "preview-render/",
                self.admin_site.admin_view(self.preview_render_view),
                name="%s_%s_preview_render" % info,
            ),
        ]
        return preview_urls + super().get_urls()

    def preview_detect_view(self, request):
        """Return a best-effort context scaffold for the posted template."""
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return HttpResponseForbidden()
        content = request.POST.get("content", "")
        scaffold = build_context_scaffold(content)
        return JsonResponse(
            {"context": json.dumps(scaffold, indent=2, ensure_ascii=False)}
        )

    def preview_render_view(self, request):
        """Render the posted template with the posted JSON context.

        Any failure (invalid JSON, unknown tag, template syntax/render error,
        misconfigured engine) is reported as a readable ``error`` with HTTP 400
        rather than surfacing a traceback.
        """
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return HttpResponseForbidden()
        content = request.POST.get("content", "")
        raw_context = request.POST.get("context", "") or "{}"
        try:
            context = json.loads(raw_context)
            if not isinstance(context, dict):
                raise ValueError(_("Context must be a JSON object."))
            html = engines["django"].from_string(content).render(context)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"html": html})

    def invalidate_cache(self, request, queryset):
        for template in queryset:
            remove_cached_template(template)
        count = queryset.count()
        message = ngettext(
            "Cache of one template successfully invalidated.",
            "Cache of %(count)d templates successfully invalidated.",
            count)
        self.message_user(request, message % {'count': count})
    invalidate_cache.short_description = _("Invalidate cache of "
                                           "selected templates")

    def repopulate_cache(self, request, queryset):
        for template in queryset:
            add_template_to_cache(template)
        count = queryset.count()
        message = ngettext(
            "Cache successfully repopulated with one template.",
            "Cache successfully repopulated with %(count)d templates.",
            count)
        self.message_user(request, message % {'count': count})
    repopulate_cache.short_description = _("Repopulate cache with "
                                           "selected templates")

    def check_syntax(self, request, queryset):
        errors = []
        for template in queryset:
            valid, error = check_template_syntax(template)
            if not valid:
                errors.append(f'{template.name}: {error}')
        if errors:
            count = len(errors)
            message = ngettext(
                "Template syntax check FAILED for %(names)s.",
                "Template syntax check FAILED for "
                "%(count)d templates: %(names)s.",
                count)
            self.message_user(request, message %
                              {'count': count, 'names': ', '.join(errors)})
        else:
            count = queryset.count()
            message = ngettext(
                "Template syntax OK.",
                "Template syntax OK for %(count)d templates.", count)
            self.message_user(request, message % {'count': count})
    check_syntax.short_description = _("Check template syntax")

    def site_list(self, template):
        return ", ".join([site.name for site in template.sites.all()])
    site_list.short_description = _('sites')


admin.site.register(Template, TemplateAdmin)
