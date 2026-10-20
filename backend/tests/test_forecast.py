import numpy as np
import pandas as pd
import pytest

from app import config
from app.services import forecast_features as ff, forecast_serving as fs


def test_latest_available_week_and_rejected_unavailable_week():
    panel = pd.DataFrame({'semana': [202550, 202551]})
    assert fs._parse_semana(None, panel) == 202551
    assert fs._parse_semana('', panel) == 202551
    assert fs._parse_semana('2025-W50', panel) == 202550
    with pytest.raises(ValueError, match='sem dados completos'):
        fs._parse_semana('2026-W01', panel)
    with pytest.raises(ValueError, match='Semana inválida'):
        fs._parse_semana('2025-W99', panel)


def test_new_snapshot_invalidates_in_memory_panel(monkeypatch):
    calls = []
    def build():
        calls.append(1)
        df = pd.DataFrame({f: [1.0] for f in ff.FEATURES})
        df['semana'] = 202501 + len(calls)
        return df
    monkeypatch.setattr(ff, 'build_panel', build)
    monkeypatch.setattr(ff, 'add_features', lambda x: x)
    assert fs.get_featured_panel().semana.iloc[0] == 202502
    assert fs.get_featured_panel().semana.iloc[0] == 202502
    config.SYNC_DIR.mkdir()
    (config.SYNC_DIR / 'current.json').write_text('{}')
    assert fs.get_featured_panel().semana.iloc[0] == 202503
    assert len(calls) == 2


def test_partial_week_is_not_eligible_for_any_neighborhood(monkeypatch):
    df = pd.DataFrame({f: [1., 1., 1., 1.] for f in ff.FEATURES})
    df['semana'] = [202501, 202501, 202502, 202502]
    df.loc[3, 'chuva_roll4'] = np.nan
    monkeypatch.setattr(ff, 'build_panel', lambda: df)
    monkeypatch.setattr(ff, 'add_features', lambda x: x)
    assert fs.get_featured_panel().semana.tolist() == [202501, 202501]


def test_real_offline_api_selects_last_common_week_and_reports_sources():
    from app.main import app
    client = app.test_client()
    response = client.post('/prioridade', json={'horizonte': 1})
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    assert len(data['todos']) == 94
    assert data['semana_cod'] == max(data['semanas_disponiveis'])
    assert data['semana_cod'] == 202552
    assert data['fontes']['clima'] == 'APAC (chuva) + Open-Meteo (temperatura)'
    assert data['dados']['fonte_chuva'] == config.APAC_PORTAL_URL
    assert data['dados']['desatualizados'] is True
    assert data['dados']['coletado_em'] is None  # CSV versionado não é uma coleta recente.
    assert 'NaN' not in response.get_data(as_text=True)
    assert client.post('/prioridade', json={'semana_id': '2026-W01'}).status_code == 400
    assert client.post('/prioridade', json={'horizonte': 5}).status_code == 400
    selected = data['todos'][0]
    explanation = client.post('/prioridade/explicacao', json={
        'bairro_id': selected['bairro_id'], 'semana_id': data['semana_id'], 'horizonte': 1})
    assert explanation.status_code == 200
    explained = explanation.get_json()
    assert explained['casos_previstos'] == selected['metadados']['casos_previstos']
    assert len(explained['contribuicoes']) == 18
    reconstructed = np.exp(explained['base_value'] + sum(c['contribuicao'] for c in explained['contribuicoes']))
    assert abs(reconstructed - explained['casos_previstos']) < 0.051
    # O mapa usa a mesma referência do ranking.
    map_response = client.get('/mapa?semana_id=' + data['semana_id'])
    assert map_response.status_code == 200
    scores = {r['bairro_nome']: r['score'] for r in data['todos']}
    for feature in map_response.get_json()['features']:
        props = feature['properties']
        if props['bairro'] in scores:
            assert props['score'] == scores[props['bairro']]
