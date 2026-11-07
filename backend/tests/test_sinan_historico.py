"""Testes do build do histórico SINAN por bairro x semana (US04)."""
import pandas as pd
import pytest

from scripts.build_sinan_historico import (
    _col,
    _filtrar_descartados,
    _filtrar_municipio,
    _norm,
    _reagregar,
)

MUNICIPIO_RESIDENCIA = ["id_mn_resi", "co_municipio_residencia",
                        "id_municip", "co_municipio_notificacao"]


@pytest.fixture
def amostra_sinan():
    """Amostra mínima com bairro, semana, município e classificação final."""
    return pd.DataFrame({
        "id_mn_resi": ["261160", "260005", "261160", "261160", "999999"],
        "classi_fin": ["10", "10", "5", "3", None],
        "semana": [201602, 201602, 201602, 201603, 201603],
        "bairro": ["A", "B", "A", "A", "B"],
    })


def test_col_prioriza_municipio_de_residencia():
    df = pd.DataFrame(columns=["co_municipio_notificacao", "co_municipio_residencia"])
    assert _col(df, MUNICIPIO_RESIDENCIA) == "co_municipio_residencia"


def test_norm_remove_acentos_e_trata_sentinelas():
    assert _norm("  São José  ") == "SAO JOSE"
    assert _norm("Não Informado") is None
    assert _norm("") is None
    assert _norm(None) is None


def test_filtro_municipio_mantem_apenas_recife(amostra_sinan):
    out = _filtrar_municipio(amostra_sinan, "id_mn_resi")
    assert out["id_mn_resi"].tolist() == ["261160", "261160", "261160"]


def test_filtro_descarta_classificacao_5(amostra_sinan):
    out = _filtrar_descartados(amostra_sinan, "classi_fin")
    assert out["classi_fin"].tolist() == ["10", "10", "3", None]


def test_reagregar_grao_unico_e_ano_da_semana():
    out = pd.DataFrame({
        "bairro": ["A", "A", "A", "B"],
        "semana": [201602, 201602, 201603, 201601],
        "casos": [1, 2, 4, 7],
        "ano": [2016, 2016, 2016, 2016],
    })
    agg = _reagregar(out)
    assert list(agg.columns) == ["bairro", "semana", "casos", "ano"]
    assert not agg.duplicated(subset=["bairro", "semana"]).any()
    linha = agg[(agg["bairro"] == "A") & (agg["semana"] == 201602)].iloc[0]
    assert linha["casos"] == 3
    assert linha["ano"] == 2016
