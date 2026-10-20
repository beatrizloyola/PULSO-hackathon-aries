from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from app import config
from app.services import apac_client as apac, data_sync as sync

FIXTURE = Path(__file__).parent / 'fixtures/apac_recife_2026_09_20_23.html'


def test_official_table_decimal_zero_and_missing_are_distinct():
    df = apac.parse_diario(FIXTURE.read_text(), date(2026, 9, 20), date(2026, 9, 23))
    areias = df[df.estacao == '261160621A'].set_index('data')
    assert areias.loc['2026-09-20', 'chuva_mm'] == 2.4
    assert areias.loc['2026-09-21', 'chuva_mm'] == 0
    ibura = df[df.estacao == '261160615A']
    assert ibura.data.tolist() == ['2026-09-20']  # Os outros três dias são '-'.
    assert df.data.min() == '2026-09-20'
    assert df.data.max() == '2026-09-23'
    assert not df.duplicated(['estacao', 'data']).any()


@pytest.mark.parametrize('html', ['<html>Manutenção</html>', '<table><tr><th>Outro formato</th></tr></table>'])
def test_changed_layout_is_rejected(html):
    with pytest.raises(ValueError, match='formato alterado'):
        apac.parse_diario(html, date(2026, 9, 20), date(2026, 9, 23))


def test_invalid_rain_is_rejected():
    html = FIXTURE.read_text().replace('2,40', '-2,40')
    with pytest.raises(ValueError, match='precipitação inválida'):
        apac.parse_diario(html, date(2026, 9, 20), date(2026, 9, 23))


def test_form_matches_official_portal():
    session = Mock()
    session.post.return_value.text = FIXTURE.read_text()
    apac.download_diario(session, date(2026, 9, 20), date(2026, 9, 23))
    args, kwargs = session.post.call_args
    assert args == (config.APAC_HISTORICO_DIARIO_URL,)
    assert kwargs['data'] == {
        'mesorregiao': 'Metropolitana de Recife', 'microrregiao': 'Todas',
        'municipio': 'Recife', 'bacia': 'Todas', 'tipoBoletim': 'Diário',
        'dataInicial': '2026-09-20', 'dataFinal': '2026-09-23',
    }


def weather_input(start='2024-12-29', end='2025-01-04'):
    days = pd.date_range(start, end).strftime('%Y-%m-%d')
    readings = pd.DataFrame([{'data': d, 'estacao': s, 'chuva_mm': v}
                             for d in days for s, v in [('A', 10), ('B', 20)]])
    temperatures = pd.DataFrame({'data': days, 'temp_media': 27, 'temp_max': 30})
    return readings, temperatures


def test_spatial_mean_then_temporal_sum_and_year_boundary():
    readings, temperatures = weather_input()
    week = sync.aggregate_weather(readings, temperatures).iloc[0]
    assert week.semana == 202501
    assert week.chuva_mm == 105  # 7 dias × média de 15 mm, não soma dos pluviômetros.
    assert week.dias == 7
    assert week.n_est == 2


def test_missing_day_does_not_become_dry_day():
    readings, temperatures = weather_input()
    readings = readings[readings.data != '2025-01-02']
    week = sync.aggregate_weather(readings, temperatures).iloc[0]
    assert week.dias == 6
    assert pd.isna(week.chuva_mm)
    assert sync.eligible_weeks(pd.DataFrame([week]), [202501]) == []


def test_missing_temperature_makes_week_ineligible():
    readings, temperatures = weather_input()
    temperatures.loc[3, 'temp_media'] = None
    week = sync.aggregate_weather(readings, temperatures).iloc[0]
    assert week.dias == 6
    assert pd.isna(week.chuva_mm)


def test_missing_apac_cache_does_not_fall_back_to_another_rain_source(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CACHE_DIR', tmp_path)
    assert apac.get_clima_semana(2026).empty


def test_no_week_can_skip_a_gap_in_its_four_lags():
    weather = pd.DataFrame({'semana': list(range(202401, 202408)), 'dias': 7})
    assert sync.eligible_weeks(weather, list(range(202401, 202408))) == [202405, 202406, 202407]
    weather.loc[weather.semana == 202403, 'dias'] = 6
    assert sync.eligible_weeks(weather, list(range(202401, 202408))) == []
