"""Best-effort context introspection for Django template strings.

This module analyses a template's *source* using Django's tokenizer
(``django.template.base.Lexer``) rather than compiling it. Tokenizing never
raises on ``{% load unknown %}`` or unknown custom tags -- it only splits the
source into TEXT / VAR / BLOCK / COMMENT tokens -- which keeps introspection
robust against templates the current environment cannot fully compile.

The single public entry point, :func:`build_context_scaffold`, returns a plain,
JSON-serialisable dict of placeholder values that a user can hand-edit before
rendering a preview. It never raises; unrecognised constructs are skipped.
"""

import copy

from django.template.base import Lexer, TokenType

__all__ = ["build_context_scaffold"]


def _is_identifier(segment):
    """True if ``segment`` is a plain Python-style identifier."""
    return bool(segment) and segment.isidentifier()


def _leaf_value(path_segments, full_path):
    """Return the placeholder leaf value for a dotted path.

    ``id`` / ``pk`` / ``*_id`` leaves become the integer ``1``; everything else
    becomes a readable string equal to the full dotted variable path.
    """
    leaf = path_segments[-1]
    if leaf in ("id", "pk") or leaf.endswith("_id"):
        return 1
    return full_path


def _record_path(target, segments, full_path):
    """Record a dotted ``segments`` path into the ``target`` dict.

    Non-leaf segments become nested dicts (a scalar occupying a slot that later
    needs to be a parent is upgraded to a dict -- parent wins). The leaf value
    follows :func:`_leaf_value`. A scalar leaf never overwrites an existing
    dict at the same slot (dict/parent reading wins).
    """
    node = target
    for i, seg in enumerate(segments):
        is_leaf = i == len(segments) - 1
        if is_leaf:
            existing = node.get(seg)
            if isinstance(existing, dict):
                # Parent-of-attributes reading already won for this name; do not
                # clobber it with a scalar.
                return
            node[seg] = _leaf_value(segments, full_path)
        else:
            existing = node.get(seg)
            if not isinstance(existing, dict):
                node[seg] = {}
            node = node[seg]


def _split_var(contents):
    """Return the cleaned dotted path segments for a VAR token, or ``None``.

    Filters are dropped (everything from the first ``|``). Only a pure dotted
    identifier chain is accepted; literals and other expressions yield ``None``.
    """
    head = contents.split("|", 1)[0].strip()
    if not head:
        return None
    segments = head.split(".")
    if not all(_is_identifier(seg) for seg in segments):
        return None
    return segments


def _parse_for(contents):
    """Parse a ``for`` block's contents into ``(targets, seq_segments)``.

    ``targets`` is the list of loop-target names (possibly several). ``seq``
    is the cleaned dotted-path segments of the iterated sequence (filters and a
    trailing ``reversed`` are dropped), or ``None`` if it is not a plain
    variable. Returns ``None`` if the block is not a well-formed ``for``.
    """
    parts = contents.split()
    # parts[0] == "for"; needs at least "for", <target>, "in", <seq>.
    if len(parts) < 4 or "in" not in parts:
        return None
    in_index = parts.index("in")
    target_tokens = parts[1:in_index]
    seq_tokens = parts[in_index + 1 :]
    if not target_tokens or not seq_tokens:
        return None
    # Drop a trailing ``reversed`` modifier (not modelled in v1).
    if seq_tokens[-1] == "reversed":
        seq_tokens = seq_tokens[:-1]
    # Loop targets are comma-separated (``for k, v in ...``); joining on space
    # then splitting on comma turns both ``k,v`` and ``k, v`` into clean names.
    targets = [t.strip() for t in " ".join(target_tokens).split(",")]
    targets = [t for t in targets if t]
    if not targets or not all(_is_identifier(t) for t in targets):
        return None
    # ``seq`` is the dotted path of the iterated sequence, or ``None`` when it
    # cannot be modelled as a plain variable (literal, multi-token, filtered).
    # We still return the targets so their accesses can be treated as opaque.
    seq = _split_var(seq_tokens[0]) if len(seq_tokens) == 1 else None
    return targets, seq


class _Scope:
    """An active ``for``-loop scope on the introspection stack."""

    __slots__ = ("var", "targets", "seq_list", "element_shape", "opaque")

    def __init__(self, var, targets, seq_list, opaque):
        # The single loop-target name (single-target loops); None when opaque.
        self.var = var
        # All loop-target names, so opaque multi-target accesses are recognised.
        self.targets = set(targets)
        # The list object living in the parent context that we attach samples to.
        self.seq_list = seq_list
        # Collected element shape for a single-target loop.
        self.element_shape = {}
        # True for multi-target loops whose targets are opaque.
        self.opaque = opaque


def _flush_scope(scope):
    """Attach exactly 2 sample elements (deep copies) to the scope's list."""
    if scope.opaque:
        # Opaque multi-target loop (``for k, v in ...``): the element shape is
        # unknown, so use a readable string placeholder rather than ``null``.
        sample = "_".join(sorted(scope.targets))
    elif not scope.element_shape:
        # Bare loop variable (``{{ item }}``): elements are strings equal to the
        # loop-variable name.
        sample = scope.var
    else:
        sample = scope.element_shape
    scope.seq_list.append(copy.deepcopy(sample))
    scope.seq_list.append(copy.deepcopy(sample))


def build_context_scaffold(content):
    """Best-effort context scaffold for a Django template string.

    Never raises: unrecognised constructs are skipped. The result is intended
    to be serialised to JSON and hand-edited by the user.
    """
    context = {}
    stack = []
    try:
        tokens = Lexer(content).tokenize()
        for token in tokens:
            ttype = token.token_type
            if ttype == TokenType.BLOCK:
                _handle_block(token.contents, context, stack)
            elif ttype == TokenType.VAR:
                _handle_var(token.contents, context, stack)
            # TEXT and COMMENT tokens carry no context variables.
        # Flush any unterminated loops.
        while stack:
            _flush_scope(stack.pop())
    except Exception:
        # Never raise: flush what we can and return whatever was collected.
        try:
            while stack:
                _flush_scope(stack.pop())
        except Exception:
            pass
    return context


def _active_scope_for(name, stack):
    """Return the innermost active scope owning loop target ``name``, or None."""
    for scope in reversed(stack):
        if name in scope.targets:
            return scope
    return None


def _handle_block(contents, context, stack):
    contents = contents.strip()
    if contents.startswith("for ") or contents == "for":
        parsed = _parse_for(contents)
        if parsed is None:
            # Malformed ``for`` header: push an opaque throwaway scope so the
            # matching ``endfor`` pops IT rather than unbalancing an enclosing
            # loop.
            stack.append(_Scope(None, (), [], True))
            return
        targets, seq = parsed
        if seq is None:
            # Targets parse but the sequence cannot be modelled (literal,
            # filtered, multi-token): opaque scope that OWNS the targets, so
            # their accesses are dropped instead of leaking to the top level.
            # A throwaway list keeps its samples out of the context.
            stack.append(_Scope(None, targets, [], True))
            return
        # Register the seq as a list in the top-level context. Loop
        # registration wins over any stray scalar/attr access on the same name.
        seq_list = _register_seq_list(context, seq)
        if seq_list is None:
            # Could not model the seq as a top-level list (e.g. collides with an
            # existing dict); still push a scope so the matching endfor balances,
            # but with a throwaway list.
            seq_list = []
        opaque = len(targets) != 1
        var = None if opaque else targets[0]
        stack.append(_Scope(var, targets, seq_list, opaque))
    elif contents == "endfor" or contents.startswith("endfor "):
        if stack:
            _flush_scope(stack.pop())


def _register_seq_list(context, seq_segments):
    """Ensure ``seq_segments`` resolves to a list in the top-level context.

    Only simple (single-segment) sequence names are modelled as top-level
    lists. Returns the list object to attach samples to, or ``None`` if it
    cannot be represented.
    """
    if len(seq_segments) != 1:
        return None
    name = seq_segments[0]
    existing = context.get(name)
    if isinstance(existing, list):
        return existing
    # Loop registration wins: overwrite a stray scalar/dict with a fresh list.
    new_list = []
    context[name] = new_list
    return new_list


def _handle_var(contents, context, stack):
    segments = _split_var(contents)
    if segments is None:
        return
    first = segments[0]
    # ``forloop.*`` is a Django loop helper, never user context.
    if first == "forloop":
        return
    scope = _active_scope_for(first, stack)
    if scope is not None:
        if scope.opaque:
            # Opaque multi-target loop var: drop its accesses.
            return
        remaining = segments[1:]
        if not remaining:
            # Bare loop var (``{{ item }}``): element shape stays empty so the
            # flush emits strings.
            return
        _record_path(scope.element_shape, remaining, ".".join(segments))
        return
    # Not a loop var: record into the top-level context, unless the name is
    # already registered as a loop seq list (loop registration wins).
    if isinstance(context.get(first), list):
        return
    _record_path(context, segments, ".".join(segments))
