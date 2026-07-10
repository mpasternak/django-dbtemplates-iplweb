import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class PreviewEndpointTests(TestCase):
    """Integration tests for the admin preview-detect / preview-render views."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            "admin", "admin@example.com", "password"
        )
        cls.plain_user = User.objects.create_user("bob", "bob@example.com", "password")

    def setUp(self):
        self.detect_url = reverse("admin:dbtemplates_template_preview_detect")
        self.render_url = reverse("admin:dbtemplates_template_preview_render")

    # -- render ----------------------------------------------------------

    def test_render_valid(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            self.render_url,
            {
                "content": "Hello {{ name }}!",
                "context": json.dumps({"name": "Jan"}),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["html"], "Hello Jan!")

    def test_render_unknown_tag_is_graceful(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            self.render_url,
            {"content": "{% load nope %}hi", "context": "{}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_render_invalid_context_json(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            self.render_url,
            {"content": "{{ a }}", "context": "{not json}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    # -- detect ----------------------------------------------------------

    def test_detect_returns_scaffold(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            self.detect_url,
            {"content": "{{ user.name }}{{ object.id }}"},
        )
        self.assertEqual(resp.status_code, 200)
        context = json.loads(resp.json()["context"])
        self.assertEqual(context, {"user": {"name": "user.name"}, "object": {"id": 1}})

    # -- method / permissions -------------------------------------------

    def test_get_not_allowed(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self.detect_url).status_code, 405)
        self.assertEqual(self.client.get(self.render_url).status_code, 405)

    def test_non_staff_denied(self):
        # Anonymous is redirected to the admin login (not 200).
        self.assertNotEqual(self.client.post(self.detect_url).status_code, 200)
        # A logged-in, non-staff user is likewise refused.
        self.client.force_login(self.plain_user)
        self.assertNotEqual(self.client.post(self.detect_url).status_code, 200)
        self.assertNotEqual(self.client.post(self.render_url).status_code, 200)


class PreviewChangeFormTests(TestCase):
    """The change form ships the collapsed, sandboxed preview panel."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            "admin", "admin@example.com", "password"
        )

    def test_change_form_has_sandboxed_iframe(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:dbtemplates_template_add"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('sandbox="allow-scripts"', content)
        self.assertNotIn("allow-same-origin", content)
