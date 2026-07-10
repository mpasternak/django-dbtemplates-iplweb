"""Tests for the template-aware TinyMCE config merge (Feature A).

These exercise the pure, unit-testable ``apply_template_tinymce_config``
function directly, so they do not require an active TinyMCE widget.
"""

from django.test import SimpleTestCase, override_settings

from dbtemplates.admin import apply_template_tinymce_config


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
