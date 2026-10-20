from datetime import date, datetime
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from app import config
from app.services import data_sync as sync


def test_sinan_dates_determine_cdc_week_and_municipality():
    df = pd.DataFrame({
        'NM_BAIRRO': ['Várzea', 'Ibura', 'Outro'],
        'DT_NOTIFIC': ['29/12/2024', '04/01/2025', '04/01/2025'],
        'ID_MUNICIP': [261160, 2611606, 1261160],
        'SEM_NOT': [202452, 202452, 202501],  # Datas são a referência para normalização.
    })
    cases, first, last = sync.normalize_sinan(df)
    assert cases.casos.sum() == 2
    assert set(cases.semana) == {202501}
    assert set(cases.bairro_norm) == {'VARZEA', 'IBURA'}
    assert first == date(2024, 12, 29)
    assert last == date(2025, 1, 4)


def test_partial_case_week_is_not_available(monkeypatch):
    monkeypatch.setattr(sync, 'today', lambda: date(2025, 1, 4))
    # Mesmo havendo notificação no sábado atual, a semana não está fechada.
    assert sync.complete_case_weeks([(date(2024, 12, 29), date(2025, 1, 4))]) == []
    monkeypatch.setattr(sync, 'today', lambda: date(2025, 1, 5))
    assert sync.complete_case_weeks([(date(2024, 12, 29), date(2025, 1, 4))]) == [202501]


def test_catalog_discovers_new_year_without_hard_coding(monkeypatch):
    monkeypatch.setattr(sync, 'today', lambda: date(2026, 9, 24))
    package = {'resources': [
        {'name': 'Casos de Dengue 2026', 'format': 'CSV', 'url': 'https://example.test/2026'},
        {'name': 'Casos de Zika 2026', 'format': 'CSV'},
        {'name': 'Metadados Dengue 2026', 'format': 'JSON'},
    ]}
    assert list(sync.discover_resources(package)) == [2026]


def test_failed_collection_preserves_current_snapshot(monkeypatch):
    config.SYNC_DIR.mkdir()
    previous = {'snapshot': 'anterior', 'coletado_em': datetime.now(sync.TZ).isoformat()}
    sync.atomic_json(config.SYNC_DIR / 'current.json', previous)
    session = Mock(headers={})
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.side_effect = requests.ConnectionError('fonte indisponível')
    monkeypatch.setattr(sync.requests, 'Session', lambda: session)
    with pytest.raises(requests.ConnectionError):
        sync.sync_data(force=True)
    assert sync.read_json(config.SYNC_DIR / 'current.json') == previous
    assert 'fonte indisponível' in sync.read_json(config.SYNC_DIR / 'attempt.json')['erro']
    status = sync.data_status(202552)
    assert status['desatualizados']
    assert any('preservados' in a for a in status['avisos'])


def test_fresh_cache_makes_no_network_call():
    config.SYNC_DIR.mkdir()
    current = {'snapshot': 'existente', 'coletado_em': datetime.now(sync.TZ).isoformat()}
    sync.atomic_json(config.SYNC_DIR / 'current.json', current)
    assert sync.sync_data() == current


def test_complete_snapshot_publish_and_reload(monkeypatch):
    monkeypatch.setattr(sync, 'today', lambda: date(2024, 3, 11))
    monkeypatch.setattr(config, 'DATA_START_YEAR', 2024)
    days = pd.date_range('2024-01-01', '2024-03-10').strftime('%Y-%m-%d')
    readings = pd.DataFrame({'data': days, 'estacao': 'A', 'chuva_mm': 1.0})
    temps = pd.DataFrame({'data': days, 'temp_media': 27.0, 'temp_max': 30.0})
    monkeypatch.setattr(sync.apac_client, 'download_diario', lambda *a: (readings, '<html>fixture</html>'))
    monkeypatch.setattr(sync, 'download_temperatures', lambda *a: (temps, {}))
    catalog = Mock()
    catalog.json.return_value = {'success': True, 'result': {'resources': [
        {'name': 'Casos de Dengue 2024', 'format': 'CSV', 'url': 'https://example.test/dengue'}]}}
    resource = Mock()
    resource.content = b'NM_BAIRRO;DT_NOTIFIC;ID_MUNICIP\nIBURA;01/01/2024;261160\nIBURA;09/03/2024;261160\n'
    session = Mock(headers={})
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.side_effect = [catalog, resource]
    monkeypatch.setattr(sync.requests, 'Session', lambda: session)
    result = sync.sync_data(force=True)
    cases, weather, meta = sync.load_snapshot()
    assert result == meta
    assert cases.casos.sum() == 2
    assert meta['casos_ate'] == '2024-03-09'
    assert meta['chuva_ate'] == '2024-03-10'
    assert meta['ultima_semana_comum'] == 202410
    assert len(meta['consultas_apac'][0]['sha256']) == 64
    assert weather.loc[weather.semana == 202410, 'chuva_mm'].iloc[0] == 7
