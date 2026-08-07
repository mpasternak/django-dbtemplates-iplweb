"""Settings variant that enables the TinyMCE editor path.

Used only by the subprocess test in ``test_tinymce_widget.py`` so the
``SourceAwareAdminTinyMCE`` branch of ``dbtemplates.admin`` (which is selected
at import time) can be exercised in a fresh interpreter, without reloading
``admin.py`` in-process (that would re-run ``admin.site.register`` and raise
``AlreadyRegistered``).
"""

from dbtemplates.test_settings import *  # noqa: F401,F403

DBTEMPLATES_USE_TINYMCE = True
