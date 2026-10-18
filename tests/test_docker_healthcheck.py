import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("docker_healthcheck", Path(__file__).parents[1] / "scripts/docker-healthcheck.py")
healthcheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(healthcheck)


@pytest.mark.parametrize("body,expected", [
    (b'{"status":"healthy","success":true}', 0),
    (b'{"status":"unhealthy","success":true}', 1),
    (b'{"status":"healthy","success":false}', 1),
    (b'<html>Login</html>', 1),
    (b'[]', 1),
])
def test_health_requires_explicit_success(body, expected):
    with patch.object(healthcheck, "urlopen") as opener:
        response = opener.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = body
        assert healthcheck.main() == expected


def test_health_connection_failure():
    with patch.object(healthcheck, "urlopen", side_effect=OSError("unreachable")):
        assert healthcheck.main() == 1
