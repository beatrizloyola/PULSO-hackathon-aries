import os
import sys
from pathlib import Path

os.environ['AUTO_SYNC'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import requests
from app import config
from app.services import forecast_serving


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'SYNC_DIR', tmp_path / 'atualizacao')
    monkeypatch.setattr(forecast_serving, '_featured_panel', None)
    monkeypatch.setattr(forecast_serving, '_panel_signature', None)
    def no_network(*args, **kwargs):
        raise AssertionError('Os testes não devem acessar a rede')
    monkeypatch.setattr(requests.Session, 'request', no_network)
