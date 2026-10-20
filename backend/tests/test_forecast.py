import math

import numpy as np
import pandas as pd
import pytest

from app import config
from app.services import forecast_features as ff, forecast_serving as fs
from scripts.export_model import gate

SEMANA = "2025-W30"


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return app.test_client()


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


def test_real_offline_api_selects_last_common_week_and_reports_sources(client):
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
    assert explained['casos_previstos'] == pytest.approx(selected['metadados']['casos_previstos'], abs=0.051)
    assert explained['dados']['fonte_chuva'] == config.APAC_PORTAL_URL
    assert len(explained['contribuicoes']) == 18
    # O mapa usa a mesma referência do ranking.
    map_response = client.get('/mapa?semana_id=' + data['semana_id'])
    assert map_response.status_code == 200
    scores = {r['bairro_nome']: r['score'] for r in data['todos']}
    for feature in map_response.get_json()['features']:
        props = feature['properties']
        if props['bairro'] in scores:
            assert props['score'] == scores[props['bairro']]


@pytest.mark.parametrize("horizonte", [1, 4])
def test_explicacao_reconstroi_a_previsao_do_ranking(client, horizonte):
    ranking = client.post("/prioridade", json={"semana_id": SEMANA, "horizonte": horizonte}).json
    for item in ranking["todos"][:5]:
        exp = client.post("/prioridade/explicacao", json={
            "bairro_id": item["bairro_id"], "semana_id": SEMANA, "horizonte": horizonte,
        }).json
        soma_log = exp["base_value"] + sum(c["contribuicao"] for c in exp["contribuicoes"])
        assert math.exp(soma_log) == pytest.approx(item["metadados"]["casos_previstos"], abs=0.1)
        assert exp["score"] == pytest.approx(item["score"], abs=0.5)


def _m(mae_xgb, mae_p, pk_xgb, pk_p):
    return {"mae_xgb": mae_xgb, "mae_persistencia": mae_p,
            "precisao_k_xgb": pk_xgb, "precisao_k_persistencia": pk_p}


def test_gate_aprova_quando_bate_persistencia_em_todos_horizontes():
    assert gate({"h1": _m(1.2, 1.3, 0.6, 0.5), "h2": _m(1.3, 1.4, 0.55, 0.55)}) == []


@pytest.mark.parametrize("metricas", [
    _m(1.3, 1.3, 0.6, 0.5),    # MAE empata com persistência
    _m(1.4, 1.3, 0.6, 0.5),    # MAE pior
    _m(1.2, 1.3, 0.4, 0.5),    # P@K pior
    _m(1.2, 1.3, None, 0.5),   # P@K não calculável
])
def test_gate_reprova_horizonte_que_nao_bate_persistencia(metricas):
    falhas = gate({"h1": _m(1.2, 1.3, 0.6, 0.5), "h3": metricas})
    assert len(falhas) == 1 and falhas[0].startswith("h3")
