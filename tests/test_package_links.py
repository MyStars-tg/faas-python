"""The package points readers at the MyStars API landing and the store.

PyPI and GitHub render these links on the package page; they are how a
developer who found the SDK reaches the product it is for.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVELOPERS_URL = "https://mystars.tg/developers"
STORE_URL = "https://mystars.tg"


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _project_url(label):
    urls = _read("pyproject.toml").split("[project.urls]", 1)[1].split("\n[", 1)[0]
    # A TOML key containing a dot must be quoted ("MyStars.tg"); a plain one may not be.
    match = re.search(rf'^"?{re.escape(label)}"?\s*=\s*"([^"]+)"', urls, re.M)
    return match.group(1) if match else None


def test_the_homepage_is_the_api_landing():
    assert _project_url("Homepage") == DEVELOPERS_URL


def test_the_store_is_listed_among_the_project_links():
    assert _project_url("MyStars.tg") == STORE_URL


def test_the_readme_links_the_api_landing_and_the_store():
    readme = _read("README.md")
    assert f"]({DEVELOPERS_URL})" in readme
    assert f"]({STORE_URL})" in readme
