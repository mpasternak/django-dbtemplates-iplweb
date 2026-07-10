"""Unit tests for ``build_context_scaffold`` (context introspection).

The tests assert exact expected dicts so the introspection output stays fully
deterministic, and pin the internal tokenizer contract so a Django upgrade that
changes it fails loudly.
"""

from django.template.base import Lexer, TokenType
from django.test import SimpleTestCase

from dbtemplates.utils.introspect import build_context_scaffold


class TokenizerContractTests(SimpleTestCase):
    """Pin the internal ``django.template.base`` API introspection relies on."""

    def test_token_types_exist(self):
        for name in ("TEXT", "VAR", "BLOCK", "COMMENT"):
            self.assertTrue(hasattr(TokenType, name))

    def test_lexer_tokenizes_without_raising_on_unknown_load(self):
        tokens = Lexer("{% load unknown_lib %}{{ title }}").tokenize()
        self.assertEqual(tokens[0].token_type, TokenType.BLOCK)
        self.assertEqual(tokens[0].contents, "load unknown_lib")


class BuildContextScaffoldTests(SimpleTestCase):
    def test_plain_variable(self):
        self.assertEqual(build_context_scaffold("{{ title }}"), {"title": "title"})

    def test_attribute_access(self):
        self.assertEqual(
            build_context_scaffold("{{ user.name }}"),
            {"user": {"name": "user.name"}},
        )

    def test_id_leaf_is_integer(self):
        self.assertEqual(
            build_context_scaffold("{{ object.id }}"),
            {"object": {"id": 1}},
        )

    def test_pk_leaf_is_integer(self):
        self.assertEqual(build_context_scaffold("{{ pk }}"), {"pk": 1})

    def test_underscore_id_leaf_is_integer(self):
        self.assertEqual(build_context_scaffold("{{ author_id }}"), {"author_id": 1})

    def test_filters_are_stripped(self):
        self.assertEqual(
            build_context_scaffold("{{ user.name|upper }}"),
            {"user": {"name": "user.name"}},
        )

    def test_for_loop_element_shape(self):
        self.assertEqual(
            build_context_scaffold(
                "{% for item in items %}{{ item.title }}{% endfor %}"
            ),
            {"items": [{"title": "item.title"}, {"title": "item.title"}]},
        )

    def test_bare_loop_variable(self):
        self.assertEqual(
            build_context_scaffold("{% for x in xs %}{{ x }}{% endfor %}"),
            {"xs": ["x", "x"]},
        )

    def test_forloop_helper_is_ignored(self):
        self.assertEqual(
            build_context_scaffold(
                "{% for x in xs %}{{ forloop.counter }}{% endfor %}"
            ),
            {"xs": ["x", "x"]},
        )

    def test_scalar_then_dict_collision_dict_wins(self):
        self.assertEqual(
            build_context_scaffold("{{ user }}{{ user.name }}"),
            {"user": {"name": "user.name"}},
        )

    def test_list_vs_dict_collision_list_wins(self):
        self.assertEqual(
            build_context_scaffold(
                "{% for x in things %}{% endfor %}{{ things.count }}"
            ),
            {"things": ["x", "x"]},
        )

    def test_unterminated_for_loop_flushes(self):
        self.assertEqual(
            build_context_scaffold("{% for x in xs %}{{ x.a }}"),
            {"xs": [{"a": "x.a"}, {"a": "x.a"}]},
        )

    def test_unknown_load_does_not_raise(self):
        self.assertEqual(
            build_context_scaffold("{% load unknown_lib %}{{ title }}"),
            {"title": "title"},
        )

    def test_multitarget_for_with_space_is_opaque_list(self):
        # ``for k, v`` (space after comma) must still register ``items`` as a
        # list and treat the targets as opaque (their accesses dropped), not
        # leak ``v`` into the top-level context.
        self.assertEqual(
            build_context_scaffold("{% for k, v in items %}{{ v.name }}{% endfor %}"),
            {"items": ["k_v", "k_v"]},
        )

    def test_unparseable_inner_for_does_not_unbalance_outer_loop(self):
        # The inner loop iterates a literal (unparseable seq); it must not flush
        # the outer loop early or mis-attribute ``row.title``.
        self.assertEqual(
            build_context_scaffold(
                "{% for row in rows %}"
                "{% for x in 'abc' %}{{ x }}{% endfor %}"
                "{{ row.title }}"
                "{% endfor %}"
            ),
            {"rows": [{"title": "row.title"}, {"title": "row.title"}]},
        )
