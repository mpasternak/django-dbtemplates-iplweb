"""Optional optimisation: skip cache/DB lookups for names not in the DB.

The loader normally consults its cache (and, on a miss, the ``django_template``
table) for *every* template name Django resolves. A single Django-admin page
renders ~150 ``admin/`` / ``grappelli/`` framework partials, none of which are
ever stored in the DB — yet each one triggers a lookup. With a no-op cache
backend (``DummyCache``, common in development so template edits show up
immediately) that is hundreds of wasted ``SELECT ... FROM django_template``
queries per page; with a shared cache (Redis) it is hundreds of redundant
cache round-trips.

When ``DBTEMPLATES_SKIP_UNKNOWN_NAMES`` is enabled this module keeps an
in-process set of the names that actually exist in the ``Template`` table and
lets the loader answer "not here, try the next loader" for any name outside
it, without touching the cache or the database. Names that *are* in the set
fall through to the normal loader machinery, so per-site resolution, caching
and overrides keep working unchanged.

The set is loaded lazily on first use and dropped whenever a ``Template`` row
is saved or deleted (see the signal hooks in ``dbtemplates.models``). Because
the set lives in a single process, changes made by *other* processes (multiple
web workers, or rows inserted via raw SQL / ``loaddata``) are not seen until
that process reloads the set. Serving processes reload it on restart, so a
deploy always picks up new templates; to bound the staleness window without a
restart set ``DBTEMPLATES_KNOWN_NAMES_TTL`` to a number of seconds.
"""

import threading
import time

from django.db import DatabaseError

from dbtemplates.conf import settings

_lock = threading.Lock()
_names = None  # frozenset[str] | None ; None means "not loaded"
_loaded_at = 0.0  # time.monotonic() of the last successful load


def _load():
    # Imported lazily so this module can be imported from ``dbtemplates.models``
    # without a circular import.
    from dbtemplates.models import Template

    return frozenset(Template.objects.values_list("name", flat=True))


def invalidate_known_names(**kwargs):
    """Signal receiver: drop the cached set so it is reloaded on next use."""
    global _names
    with _lock:
        _names = None


def _ttl():
    ttl = getattr(settings, "DBTEMPLATES_KNOWN_NAMES_TTL", None)
    return ttl if ttl and ttl > 0 else None


def _expired(ttl):
    return ttl is not None and (time.monotonic() - _loaded_at) >= ttl


def known_names():
    """Return the set of names present in the DB, or ``None`` if unknown.

    ``None`` (e.g. before the table has been migrated) makes callers fall back
    to the normal loader path, so a legitimate override is never masked.
    """
    global _names, _loaded_at
    ttl = _ttl()
    if _names is not None and not _expired(ttl):
        return _names
    with _lock:
        if _names is None or _expired(ttl):
            try:
                _names = _load()
            except DatabaseError:
                # Table not available yet (fresh DB / mid-migrate). Fall back
                # to the normal loader path rather than masking templates.
                return None
            _loaded_at = time.monotonic()
    return _names


def should_skip(template_name):
    """Whether the loader may skip cache/DB lookups for ``template_name``."""
    if not getattr(settings, "DBTEMPLATES_SKIP_UNKNOWN_NAMES", False):
        return False
    names = known_names()
    return names is not None and template_name not in names
