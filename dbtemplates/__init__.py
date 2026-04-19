import importlib.metadata

try:
    __version__ = importlib.metadata.version("django-dbtemplates-iplweb")
except importlib.metadata.PackageNotFoundError:
    # Fallback for environments where the package was installed under the
    # upstream distribution name.
    try:
        __version__ = importlib.metadata.version("django-dbtemplates")
    except importlib.metadata.PackageNotFoundError:
        __version__ = "0.0.0"
