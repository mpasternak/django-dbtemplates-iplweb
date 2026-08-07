"""Tests for the template-aware TinyMCE config merge (Feature A).

These exercise the pure, unit-testable ``apply_template_tinymce_config``
function directly, so they do not require an active TinyMCE widget.
"""

import os
import subprocess
import sys

from django.test import SimpleTestCase, override_settings

from dbtemplates.admin import apply_template_tinymce_config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ApplyTemplateTinyMCEConfigTests(SimpleTestCase):
    def test_dbtemplates_overrides_are_set(self):
        result = apply_template_tinymce_config({})
        self.assertEqual(result["entity_encoding"], "raw")
        self.assertIs(result["verify_html"], False)
        self.assertIs(result["convert_urls"], False)

    def test_does_not_mutate_input(self):
        config = {"plugins": "link"}
        apply_template_tinymce_config(config)
        self.assertEqual(config, {"plugins": "link"})

    # --- plugins normalization -------------------------------------------
    def test_code_added_to_string_plugins(self):
        result = apply_template_tinymce_config({"plugins": "link image"})
        self.assertIn("code", result["plugins"])
        self.assertEqual(result["plugins"], "link image code")

    def test_code_added_to_list_plugins(self):
        result = apply_template_tinymce_config({"plugins": ["link", "image"]})
        self.assertEqual(result["plugins"], ["link", "image", "code"])

    def test_code_not_duplicated_in_string_plugins(self):
        result = apply_template_tinymce_config({"plugins": "link code image"})
        self.assertEqual(result["plugins"], "link code image")

    def test_code_not_duplicated_in_list_plugins(self):
        result = apply_template_tinymce_config({"plugins": ["code", "link"]})
        self.assertEqual(result["plugins"], ["code", "link"])

    def test_code_not_duplicated_in_comma_separated_plugins(self):
        # django-tinymce's DEFAULT_CONFIG ships a comma-separated plugins
        # string that already contains "code"; it must not be duplicated.
        result = apply_template_tinymce_config(
            {"plugins": "advlist,autolink,code,fullscreen"}
        )
        self.assertEqual(result["plugins"], "advlist,autolink,code,fullscreen")

    def test_code_added_to_comma_separated_plugins_without_code(self):
        result = apply_template_tinymce_config({"plugins": "advlist,autolink"})
        self.assertEqual(result["plugins"], "advlist,autolink code")

    def test_plugins_absent_gets_code(self):
        result = apply_template_tinymce_config({})
        self.assertIn("code", result["plugins"])

    # --- toolbar normalization -------------------------------------------
    def test_code_added_to_string_toolbar(self):
        result = apply_template_tinymce_config({"toolbar": "bold italic"})
        self.assertIn("code", result["toolbar"])

    def test_code_added_to_list_toolbar(self):
        result = apply_template_tinymce_config({"toolbar": ["bold italic"]})
        self.assertIn("code", result["toolbar"])

    def test_code_not_duplicated_in_string_toolbar(self):
        result = apply_template_tinymce_config({"toolbar": "bold code italic"})
        self.assertEqual(result["toolbar"], "bold code italic")

    def test_code_not_duplicated_in_list_toolbar(self):
        result = apply_template_tinymce_config({"toolbar": ["bold italic", "code"]})
        self.assertEqual(result["toolbar"], ["bold italic", "code"])

    def test_toolbar_false_left_untouched(self):
        result = apply_template_tinymce_config({"toolbar": False})
        self.assertIs(result["toolbar"], False)

    def test_absent_toolbar_left_untouched(self):
        result = apply_template_tinymce_config({})
        self.assertNotIn("toolbar", result)

    # --- DBTEMPLATES_TINYMCE_CONFIG merge --------------------------------
    @override_settings(
        DBTEMPLATES_TINYMCE_CONFIG={"entity_encoding": "named", "height": 500}
    )
    def test_project_config_has_last_word_over_defaults(self):
        result = apply_template_tinymce_config({})
        # project override wins over dbtemplates default
        self.assertEqual(result["entity_encoding"], "named")
        self.assertEqual(result["height"], 500)

    @override_settings(
        DBTEMPLATES_TINYMCE_CONFIG={
            "plugins": "link image",
            "toolbar": "bold italic",
        }
    )
    def test_code_survives_project_plugins_and_toolbar(self):
        # Regression for merge-order: even when the project sets its own
        # plugins/toolbar via DBTEMPLATES_TINYMCE_CONFIG, the source-view
        # button must still be present.
        result = apply_template_tinymce_config(
            {"plugins": "somethingelse", "toolbar": "underline"}
        )
        self.assertIn("code", result["plugins"])
        self.assertEqual(result["plugins"], "link image code")
        self.assertIn("code", result["toolbar"])

    @override_settings(DBTEMPLATES_TINYMCE_CONFIG={"toolbar": False})
    def test_project_can_disable_toolbar_via_config(self):
        # toolbar:false is the deliberate opt-out; code must not resurrect it.
        result = apply_template_tinymce_config({"toolbar": "bold"})
        self.assertIs(result["toolbar"], False)


class RealDjangoTinyMCEConfigTests(SimpleTestCase):
    """Exercise the merge against django-tinymce's ACTUAL default config.

    ``apply_template_tinymce_config`` runs on top of whatever
    ``AdminTinyMCE.get_mce_config`` produces; this guards the load-bearing
    integration (a django-tinymce default-config or API change) that the pure
    unit tests above cannot catch.
    """

    def test_merge_over_real_admin_tinymce_default(self):
        from tinymce.widgets import AdminTinyMCE

        base = AdminTinyMCE().get_mce_config({"id": "id_content"})
        result = apply_template_tinymce_config(base)

        self.assertEqual(result["entity_encoding"], "raw")
        self.assertFalse(result["verify_html"])
        self.assertFalse(result["convert_urls"])
        # code ends up in plugins exactly once (django-tinymce ships it already).
        from dbtemplates.admin import _tokenize_tinymce_list

        self.assertEqual(_tokenize_tinymce_list(result["plugins"]).count("code"), 1)


class SourceAwareWidgetBranchTests(SimpleTestCase):
    """Exercise the whole ``DBTEMPLATES_USE_TINYMCE`` branch out-of-process.

    ``admin.py`` selects the editor widget at import time, so the
    ``SourceAwareAdminTinyMCE`` class, its ``get_mce_config`` override, and the
    ``protect`` JS Media ordering cannot be reached with the default settings.
    A subprocess with ``DBTEMPLATES_USE_TINYMCE=True`` loads and checks it (an
    in-process reload would re-run ``admin.site.register`` and raise
    ``AlreadyRegistered``).
    """

    def test_tinymce_branch_loads_and_configures_code(self):
        env = dict(os.environ)
        env["DJANGO_SETTINGS_MODULE"] = "dbtemplates.test_settings_tinymce"
        env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, os.path.join("dbtemplates", "_tinymce_widget_check.py")],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("OK", result.stdout)
