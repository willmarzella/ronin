import os

import pytest


@pytest.fixture
def camofox_url() -> str:
    """URL of a live camofox-browser server for tests/test_camofox_ecs.py.

    Those checks drive a real browser, so without CAMOFOX_URL they skip rather
    than fail. Run as a script, that file passes the URL itself.
    """
    url = os.environ.get("CAMOFOX_URL")
    if not url:
        pytest.skip("set CAMOFOX_URL to a running camofox-browser server")
    return url
