# django-dbtemplates-iplweb

[![PyPI](https://img.shields.io/pypi/v/django-dbtemplates-iplweb.svg)](https://pypi.org/project/django-dbtemplates-iplweb/)
[![Tests](https://github.com/mpasternak/django-dbtemplates-iplweb/actions/workflows/test.yml/badge.svg)](https://github.com/mpasternak/django-dbtemplates-iplweb/actions/workflows/test.yml)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Django Version](https://img.shields.io/badge/django-4.2%20%7C%205.0%20%7C%205.1%20%7C%205.2-092e20.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-BSD-green.svg)](LICENSE)
[![Documentation](https://readthedocs.org/projects/django-dbtemplates/badge/)](https://django-dbtemplates.readthedocs.io/)

`dbtemplates` is a Django app that stores templates in the database and
exposes them through a regular Django template loader — so templates can be
edited from the admin instead of being redeployed as files.

Originally developed by Jannis Leidel and
[Jazzband](https://jazzband.co/projects/django-dbtemplates).
This fork is actively maintained by [IPLweb](https://github.com/iplweb/).

<p align="center">
<b>Support graciously provided by</b><br><br>
<a href="https://www.iplweb.pl"><img src="https://www.iplweb.pl/images/ipl-logo-large.png" alt="IPLweb" width="150"></a>
</p>

## Why?

Django's built-in template loaders read from the filesystem or app
directories. That works well for developer-owned templates, but not for
content that needs to change without a deploy (marketing copy, transactional
email bodies, error pages, site-specific overrides). `dbtemplates` adds a
loader that reads templates from a database model, so non-developers can
edit them via the admin and changes take effect immediately.

## Features

- Database-backed Django template loader — drop-in with the standard
  `TEMPLATES.OPTIONS.loaders` chain
- Edit templates through the Django admin (syntax highlighting included)
- Multi-site support via `django.contrib.sites` — the same template name can
  resolve to different content per site
- Cache integration with Django's cache framework; invalidation on save
- Management commands:
  - `sync_templates` — bidirectional sync between the database and
    filesystem templates
  - `check_template_syntax` — validate all stored templates
  - `create_error_templates` — scaffold `404.html` / `500.html` rows
- Admin actions and optional versioned storage

## Supported versions

### Python

| 3.10 | 3.11 | 3.12 | 3.13 |
|:----:|:----:|:----:|:----:|
| ✓    | ✓    | ✓    | ✓    |

### Django

| Django \ Python | 3.10 | 3.11 | 3.12 | 3.13 |
|-----------------|:----:|:----:|:----:|:----:|
| 4.2 LTS         | ✓    | ✓    | ✓    | ✓    |
| 5.0             | ✓    | ✓    | ✓    | ✗    |
| 5.1             | ✓    | ✓    | ✓    | ✓    |
| 5.2             | ✓    | ✓    | ✓    | ✓    |

Matrix derived from `tox.ini` and Django's own Python support matrix.
`djmain` (Django's unreleased `main` branch) is tested against Python
3.12 / 3.13.

## Installation

### Using uv (recommended)

```bash
uv add django-dbtemplates-iplweb
```

### Using pip

```bash
pip install django-dbtemplates-iplweb
```

The Python import name stays `dbtemplates`, so no code changes are needed
when migrating from upstream `django-dbtemplates`:

```python
from dbtemplates.models import Template
```

### From git (latest `main`)

```bash
uv add "git+https://github.com/mpasternak/django-dbtemplates-iplweb.git"
# or
pip install "git+https://github.com/mpasternak/django-dbtemplates-iplweb.git"
```

## Quick start

1. Add `dbtemplates` to `INSTALLED_APPS` alongside
   `django.contrib.sites` and `django.contrib.admin`:

   ```python
   INSTALLED_APPS = [
       "django.contrib.auth",
       "django.contrib.contenttypes",
       "django.contrib.sessions",
       "django.contrib.sites",
       "django.contrib.admin",
       "dbtemplates",
   ]
   ```

2. Add `dbtemplates.loader.Loader` to `TEMPLATES.OPTIONS.loaders`:

   ```python
   TEMPLATES = [
       {
           "BACKEND": "django.template.backends.django.DjangoTemplates",
           "OPTIONS": {
               "loaders": [
                   "django.template.loaders.filesystem.Loader",
                   "django.template.loaders.app_directories.Loader",
                   "dbtemplates.loader.Loader",
               ],
           },
       },
   ]
   ```

   Put `dbtemplates.loader.Loader` **last** to use database templates as a
   fallback, or **first** to let them override on-disk templates.

3. Apply migrations and start the server:

   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

4. Open the admin, go to *Database templates → Templates*, and create
   entries with a `name` (e.g. `blog/entry_list.html`) and template
   `content`.

See <https://django-dbtemplates.readthedocs.io/> for the complete
documentation.

## Links

- Documentation: <https://django-dbtemplates.readthedocs.io/>
- Changelog: <https://django-dbtemplates.readthedocs.io/en/latest/changelog.html>
- Upstream source: <https://github.com/jazzband/django-dbtemplates>
- This fork: <https://github.com/mpasternak/django-dbtemplates-iplweb>

## License

BSD — see [LICENSE](LICENSE) for details.
