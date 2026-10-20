import json
import unicodedata
from datetime import date
from typing import List

import numpy as np
import pandas as pd
from epiweeks import Week

from app import config
from app.services import apac_client, data_sync

HORIZONTES = [1, 2, 3, 4]

FEATURES: List[str] = [
    "casos", "casos_lag1", "casos_lag2", "casos_lag3", "roll4_mean", "trend",
    "chuva_mm", "chuva_lag2", "chuva_lag4", "chuva_roll4",
    "temp_media", "temp_max", "temp_roll4",
    "sin_woy", "cos_woy",
    "vuln", "hist", "vizinhos_ds",
]


def _norm(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s).strip().upper())
                   if unicodedata.category(c) != "Mn")


def semana_seq(anos: List[int]) -> List[int]:
    seq, w = [], Week(min(anos), 1, system="cdc")
    while w.year <= max(anos):
        seq.append(w.year * 100 + w.week)
        w += 1
    return seq


def _aggregate_sinan(year: int) -> pd.DataFrame:
    """Lê o cache do SINAN e agrega casos por bairro (normalizado) e semana."""
    path = config.CACHE_DIR / f"dengue_{year}.csv"
    df = pd.read_csv(path, sep=";", encoding="utf-8", low_memory=False)
    return data_sync.normalize_sinan(df)[0]


def build_panel(anos: List[int] = None) -> pd.DataFrame:
    lookup = json.load(open(config.BAIRROS_LOOKUP_FILE, encoding="utf-8"))
    bairros = pd.DataFrame([{
        "bairro_id": b["id"], "bairro": b["nome"], "bairro_norm": _norm(b["nome"]),
        "ds": b["ds"], "rpa": b["rpa"], "vuln": b["vulnerabilidade_score"],
        "hist": b["historico_score"],
    } for b in lookup])

    snapshot = data_sync.load_snapshot()
    if snapshot is not None:
        casos, clima, meta = snapshot
        anos = anos or meta["anos_casos"]
        weeks_with_cases = meta["semanas_casos"]
    else:
        meta = {}
        anos = anos or config.FORECAST_ANOS
        frames, periods = [], []
        for year in anos:
            raw = pd.read_csv(config.CACHE_DIR / f"dengue_{year}.csv", sep=";", low_memory=False)
            grouped, _, last = data_sync.normalize_sinan(raw)
            frames.append(grouped)
            periods.append((date(year, 1, 1), min(last, date(year, 12, 31))))
        casos = pd.concat(frames).groupby(["bairro_norm", "semana"], as_index=False)["casos"].sum()
        weeks_with_cases = data_sync.complete_case_weeks(periods)
        clima = pd.concat([apac_client.get_clima_semana(y) for y in anos], ignore_index=True)
    if clima["semana"].duplicated().any():
        raise ValueError("Clima: semanas duplicadas no histórico")

    weeks = semana_seq(anos)
    grid = bairros.assign(_k=1).merge(
        pd.DataFrame({"semana": weeks, "_k": 1}), on="_k").drop(columns="_k")
    panel = grid.merge(casos, on=["bairro_norm", "semana"], how="left")
    # Ausência de casos vira zero somente dentro da cobertura publicada.
    covered = panel["semana"].isin(weeks_with_cases)
    panel.loc[covered, "casos"] = panel.loc[covered, "casos"].fillna(0)
    panel.loc[~covered, "casos"] = np.nan
    panel = panel.merge(clima, on="semana", how="left")
    panel = panel.sort_values(["bairro", "semana"]).reset_index(drop=True)
    panel.attrs["snapshot_meta"] = meta
    return panel


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Adiciona as colunas em FEATURES ao painel. Todas usam dados <= semana t."""
    df = panel.sort_values(["bairro", "semana"]).reset_index(drop=True)
    g = df.groupby("bairro", group_keys=False)

    df["casos_lag1"] = g["casos"].shift(1)
    df["casos_lag2"] = g["casos"].shift(2)
    df["casos_lag3"] = g["casos"].shift(3)
    df["roll4_mean"] = g["casos"].transform(lambda s: s.shift(1).rolling(4).mean())
    df["trend"] = df["casos"] - df["casos_lag1"]

    df["chuva_lag2"] = g["chuva_mm"].shift(2)
    df["chuva_lag4"] = g["chuva_mm"].shift(4)
    df["chuva_roll4"] = g["chuva_mm"].transform(lambda s: s.shift(1).rolling(4).sum())
    df["temp_roll4"] = g["temp_media"].transform(lambda s: s.shift(1).rolling(4).mean())

    woy = df["semana"] % 100
    df["sin_woy"] = np.sin(2 * np.pi * woy / 52)
    df["cos_woy"] = np.cos(2 * np.pi * woy / 52)

    # sinal espacial: média de casos dos OUTROS bairros do mesmo DS na semana t
    ds_sum = df.groupby(["ds", "semana"])["casos"].transform("sum")
    ds_cnt = df.groupby(["ds", "semana"])["casos"].transform("count")
    df["vizinhos_ds"] = (ds_sum - df["casos"]) / (ds_cnt - 1).clip(lower=1)
    return df


def add_targets(df: pd.DataFrame, horizontes: List[int] = None) -> pd.DataFrame:
    """Adiciona colunas y_h{h} = casos em t+h (por bairro). Só para treino."""
    horizontes = horizontes or HORIZONTES
    g = df.groupby("bairro", group_keys=False)
    for h in horizontes:
        df[f"y_h{h}"] = g["casos"].shift(-h)
    return df
