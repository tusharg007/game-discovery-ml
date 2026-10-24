from __future__ import annotations

import json
import sys

from game_discovery.cli import main


def test_doctor_reports_supported_runtime(capsys):
    expected = 0 if sys.version_info >= (3, 11) and sys.version_info < (3, 13) else 2
    assert main(["doctor"]) == expected
    payload = json.loads(capsys.readouterr().out)
    assert payload["application"] == "game-discovery-ml"
    assert payload["python_supported"] is (expected == 0)
