"""
SP-3 — Validação temporal (rolling-origin) e vazamento: demonstrativo executável.

Reproduz o painel real do pipeline (mesmo `ff.build_panel/add_features/add_targets`
do treino) para:

  1. Quantificar o atraso de notificação do SINAN e a curva de revisão semanal
     (base da regra as-of do esquema de validação).
  2. Derivar empiricamente a fronteira de "ano epidêmico" e montar os dois
     caminhos de folds por temporada (A: ano civil CDC | B: ano epidêmico).
  3. Rodar o rolling-origin nível 2 (expanding window, passo 6 semanas, purge
     `widx + h <= origin`) com XGBoost vs persistência vs sazonal-ingênuo.
  4. Demonstrativo de inflação de métricas: KFold "aleatório" vs divisão temporal.

Saída: tabelas em markdown para embutir em docs/spikes/SP-3-rolling-origin.md.
Não grava nada em disco nem altera o pipeline de produção.

Uso:  cd backend && ./venv/bin/python notebooks/sp3_rolling_origin.py
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from epiweeks import Week

from app import config
from app.services import forecast_features as ff

SEED = 42
K = config.FORECAST_TOP_K
MIN_TRAIN_SEMANAS = 39
PASSO = 6


def md_table(df: pd.DataFrame) -> str:
    """Markdown simples sem dependência de tabulate."""
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short=7", "HEAD"],
                              cwd=config.BASE_DIR, capture_output=True,
                              text=True).stdout.strip() or "?"
    except OSError:
        return "?"


# ---------------------------------------------------------------- 1. SINAN
def analise_atraso_sinan() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Atraso DT_NOTIFIC - DT_SIN_PRI e curva de revisão por lag semanal.

    Curva de revisão: assumindo atribuição da SE por DT_SIN_PRI (recomendação do
    glossário p/ canal endêmico), que fração do total FINAL de uma SE já estava
    notificada L semanas após o fechamento dela. Só entram semanas com janela de
    observação completa (fechadas desde a última notificação do cache).
    """
    frames = []
    for ano in config.FORECAST_ANOS:
        raw = pd.read_csv(config.CACHE_DIR / f"dengue_{ano}.csv", sep=";",
                          encoding="utf-8", low_memory=False)
        muni = raw["ID_MUNICIP"].astype(str).str.replace(r"\.0$", "", regex=True)
        raw = raw[muni.isin(["261160", "2611606"])]
        notific = pd.to_datetime(raw["DT_NOTIFIC"], format="%d/%m/%Y", errors="coerce")
        sintomas = pd.to_datetime(raw["DT_SIN_PRI"], format="%d/%m/%Y", errors="coerce")
        frames.append(pd.DataFrame({"notific": notific, "sintomas": sintomas}).dropna())
    d = pd.concat(frames, ignore_index=True)
    semanas = [Week.fromdate(x.date(), system="cdc") for x in d["sintomas"]]
    d["semana_cod"] = [w.year * 100 + w.week for w in semanas]
    d["fim_semana"] = pd.to_datetime([w.enddate() for w in semanas])
    # Restringe às semanas de sintomas dentro da janela do painel: o cache SINAN
    # tem registros com DT_SIN_PRI de erro de digitação (atrasos de décadas) que
    # poluem a curva de revisão.
    d = d[(d["semana_cod"] >= config.FORECAST_ANOS[0] * 100 + 1)
          & (d["semana_cod"] <= config.FORECAST_ANOS[-1] * 100 + 100)]

    atraso_dias = (d["notific"] - d["sintomas"]).dt.days
    atraso_dias = atraso_dias[atraso_dias >= 0]
    resumo = pd.DataFrame([{
        "n": len(atraso_dias),
        "p50_dias": int(np.percentile(atraso_dias, 50)),
        "p75_dias": int(np.percentile(atraso_dias, 75)),
        "p90_dias": int(np.percentile(atraso_dias, 90)),
        "p99_dias": int(np.percentile(atraso_dias, 99)),
        "max_dias": int(atraso_dias.max()),
    }])

    ultima_notif = d["notific"].max()
    curva = []
    for L in range(0, 9):
        visiveis = d[d["fim_semana"] <= ultima_notif - pd.Timedelta(days=7 * L + 6)]
        if visiveis.empty:
            continue
        final = visiveis.groupby("semana_cod").size()
        known = (visiveis[visiveis["notific"]
                          <= pd.to_datetime(visiveis["fim_semana"])
                          + pd.Timedelta(days=7 * L)]
                 .groupby("semana_cod").size())
        cov = float(known.sum()) / float(final.sum())
        p10 = float(np.percentile(known.reindex(final.index).fillna(0) / final, 10))
        curva.append({"lag_semanas": L, "cobertura_media": round(cov, 3),
                      "cobertura_p10_semanas": round(p10, 3),
                      "n_semanas": len(final)})
    return resumo, pd.DataFrame(curva)


# ------------------------------------------------------------- 2. temporada
def perfil_e_fronteira(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """Total municipal por SE agregado por week-of-year (média dos anos);
    fronteira do ano epidêmico = mínimo da média móvel centralizada (janela 5,
    circular). Retorna (perfil, woy_fronteira)."""
    sem_tot = df.groupby("semana")["casos"].sum(min_count=1).dropna()
    prof = pd.Series(index=range(1, 54), dtype=float)
    for code, v in sem_tot.items():
        woy = code % 100
        prof[woy] = v if np.isnan(prof[woy]) else (prof[woy] + v) / 2.0
    prof = prof.dropna()
    vals = prof.to_numpy()
    ext = np.concatenate([vals[-2:], vals, vals[:2]])
    smooth = pd.Series(ext).rolling(5, center=True).mean().to_numpy()[2:2 + len(vals)]
    return prof, int(prof.index[np.argmin(smooth)])


def folds_anuais(df: pd.DataFrame, seq: list[int], widx: dict):
    """Caminho A: fronteira = virada do ano civil CDC. Caminho B: fronteira =
    woy derivada do perfil. Cada fold: treina temporadas anteriores (com purge
    aplicado por horizonte em avaliar_fold), testa a temporada seguinte."""
    anos = config.FORECAST_ANOS
    prof, woy_fron = perfil_e_fronteira(df)

    fim_ano = {a: widx[max(c for c in seq if c // 100 == a)] for a in anos}
    ini_ano = {a: widx[min(c for c in seq if c // 100 == a)] for a in anos}

    folds = []
    for ano_teste in anos[1:]:
        folds.append({"caminho": "A (ano civil)",
                      "origem": seq[fim_ano[ano_teste - 1]],
                      "i_train_max": fim_ano[ano_teste - 1],
                      "i_test_min": ini_ano[ano_teste],
                      "i_test_max": fim_ano[ano_teste]})

    def idx_fronteira(ano: int) -> int:
        alvo = ano * 100 + woy_fron
        cand = [c for c in seq if c >= alvo]
        return widx[min(cand)] if cand else fim_ano[ano]

    b1, b2 = idx_fronteira(anos[0]), idx_fronteira(anos[1])
    folds.append({"caminho": "B (ano epidêmico)", "origem": seq[b1],
                  "i_train_max": b1, "i_test_min": b1 + 1, "i_test_max": b2})
    if b2 < len(seq) - 1:
        folds.append({"caminho": "B (ano epidêmico)", "origem": seq[b2],
                      "i_train_max": b2, "i_test_min": b2 + 1,
                      "i_test_max": len(seq) - 1})
    return prof, woy_fron, folds


def folds_step(seq: list[int]) -> list[dict]:
    """Nível 2: expanding window, nova origem a cada PASSO semanas."""
    out, o = [], MIN_TRAIN_SEMANAS
    while o + PASSO <= len(seq) - 1:
        out.append({"origem": seq[o], "i_origin": o, "i_test_min": o + 1,
                    "i_test_max": o + PASSO})
        o += PASSO
    return out


# ----------------------------------------------------------- 3. avaliação
def precisao_k(test: pd.DataFrame, pred: str, truth: str, k: int):
    precs = []
    for _, grp in test.groupby("semana"):
        g = grp.dropna(subset=[pred, truth])
        if len(g) < k or g[truth].sum() == 0:
            continue
        top_p = set(g.nlargest(k, pred)["bairro"])
        top_t = set(g.nlargest(k, truth)["bairro"])
        precs.append(len(top_p & top_t) / k)
    return round(float(np.mean(precs)), 3) if precs else np.nan


def mae(test: pd.DataFrame, pred: str, truth: str):
    t = test.dropna(subset=[pred, truth])
    if t.empty:
        return np.nan
    return round(float(np.mean(np.abs(t[truth] - t[pred]))), 3)


def naive_sazonal(test: pd.DataFrame, casos_map: dict, h: int) -> pd.Series:
    """pred(y em t+h) = casos observados na mesma SE do ano anterior (t+h−52)."""
    prev_by_semana = {}
    for cod in test["semana"].unique():
        w = Week(cod // 100, cod % 100, system="cdc") + h
        prev_by_semana[cod] = (w.year - 1) * 100 + w.week
    keys = list(zip(test["bairro"], test["semana"].map(prev_by_semana)))
    return pd.Series([casos_map.get(kk, np.nan) for kk in keys],
                     index=test.index, dtype="float64")


def run_modelo(train: pd.DataFrame, ycol: str) -> xgb.XGBRegressor:
    m = xgb.XGBRegressor(**config.FORECAST_XGB_PARAMS)
    m.fit(train[ff.FEATURES], train[ycol])
    return m


def _preparar(df, train_mask, test_mask, h, casos_map):
    ycol = f"y_h{h}"
    d = df.dropna(subset=ff.FEATURES + [ycol])
    train = d[train_mask(d)]
    test = d[test_mask(d)].copy()
    if test.empty or len(train) < 200:
        return None
    test["pred"] = np.clip(run_modelo(train, ycol).predict(test[ff.FEATURES]), 0, None)
    test["persist"] = test["casos"]
    test["sazonal"] = naive_sazonal(test, casos_map, h)
    return test


def _metricas(test: pd.DataFrame, h: int) -> dict:
    ycol = f"y_h{h}"
    return {"h": h, "n_teste": len(test),
            "mae_xgb": mae(test, "pred", ycol),
            "mae_persist": mae(test, "persist", ycol),
            "mae_sazonal": mae(test, "sazonal", ycol),
            f"p{K}_xgb": precisao_k(test, "pred", ycol, K),
            f"p{K}_persist": precisao_k(test, "persist", ycol, K),
            f"p{K}_sazonal": precisao_k(test, "sazonal", ycol, K)}


def avaliar_fold(df: pd.DataFrame, fold: dict, casos_map: dict) -> list[dict]:
    """Fold anual (teste = faixa de semanas) para todos os horizontes, com purge
    `widx + h <= i_train_max` no treino."""
    linhas = []
    for h in config.FORECAST_HORIZONS:
        test = _preparar(df,
                         lambda d, h=h: d["widx"] + h <= fold["i_train_max"],
                         lambda d: (d["widx"] >= fold["i_test_min"]) & (d["widx"] <= fold["i_test_max"]),
                         h, casos_map)
        if test is not None:
            linhas.append(_metricas(test, h))
    return linhas


def avaliar_step(df: pd.DataFrame, folds: list, casos_map: dict) -> pd.DataFrame:
    """Rolling-origin nível 2: teste = próximas PASSO semanas após cada origem."""
    linhas = []
    for f in folds:
        for h in config.FORECAST_HORIZONS:
            test = _preparar(df,
                             lambda d, h=h: d["widx"] + h <= f["i_origin"],
                             lambda d: d["widx"] > f["i_origin"],
                             h, casos_map)
            if test is None:
                continue
            test = test[test["widx"] <= f["i_test_max"]]
            if test.empty:
                continue
            m = _metricas(test, h)
            m["origem"] = f["origem"]
            mx, mp = m["mae_xgb"], m["mae_persist"]
            m["skill_vs_persist"] = round(mx / mp, 3) if mp and not np.isnan(mp) else np.nan
            linhas.append(m)
    return pd.DataFrame(linhas)


def demo_vazamento(df: pd.DataFrame, seq: list[int], casos_map: dict) -> pd.DataFrame:
    """70/30 aleatório (com fuga de informação) vs 70/30 temporal com purge,
    para o MESMO tamanho de teste em linhas."""
    rng = np.random.default_rng(SEED)
    linhas = []
    for h in config.FORECAST_HORIZONS:
        ycol = f"y_h{h}"
        d = df.dropna(subset=ff.FEATURES + [ycol]).reset_index(drop=True)
        mask = rng.random(len(d)) < 0.7
        t_ale = d[~mask].copy()
        t_ale["pred"] = np.clip(run_modelo(d[mask], ycol).predict(t_ale[ff.FEATURES]), 0, None)
        t_ale["persist"] = t_ale["casos"]

        n_teste = int(len(d) * 0.3)
        origin = len(seq) - 1 - max(1, n_teste // d["bairro"].nunique())
        t_tmp = _preparar(df, lambda dd, h=h: dd["widx"] + h <= origin,
                          lambda dd: dd["widx"] > origin, h, casos_map)
        if t_tmp is None:
            continue

        ma, mt = mae(t_ale, "pred", ycol), mae(t_tmp, "pred", ycol)
        pa, pt = precisao_k(t_ale, "pred", ycol, K), precisao_k(t_tmp, "pred", ycol, K)
        linhas.append({
            "h": h, "mae_aleatorio": ma, "mae_temporal": mt,
            "mae_persist_ale": mae(t_ale, "persist", ycol),
            "mae_persist_temp": mae(t_tmp, "persist", ycol),
            f"p{K}_aleatorio": pa, f"p{K}_temporal": pt,
            "mae_inflado_%": round(100 * (mt - ma) / mt, 1) if mt and not np.isnan(mt) else np.nan,
        })
    return pd.DataFrame(linhas)


# ------------------------------------------------------------------ main
def main():
    print(f"# SP-3 rolling-origin — painel {config.FORECAST_ANOS}, seed {SEED} (git {_git_sha()})\n")

    panel = ff.build_panel(config.FORECAST_ANOS)
    df = ff.add_targets(ff.add_features(panel), config.FORECAST_HORIZONS)
    seq = ff.semana_seq(config.FORECAST_ANOS)
    widx = {c: i for i, c in enumerate(seq)}
    df["widx"] = df["semana"].map(widx)
    casos_map = {(r["bairro"], r["semana"]): r["casos"]
                 for _, r in panel[panel["casos"].notna()].iterrows()}
    print(f"Painel: {df['bairro'].nunique()} bairros × {len(seq)} semanas "
          f"({seq[0]}–{seq[-1]}).\n")

    # 1 — atraso SINAN
    resumo, curva = analise_atraso_sinan()
    print("## 1. Atraso de notificação SINAN (dias, DT_NOTIFIC − DT_SIN_PRI)\n")
    print(md_table(resumo))
    print("\n## 1b. Curva de revisão: fração do total FINAL de uma SE já notificada "
          "L semanas após o fechamento dela\n")
    print(md_table(curva))
    alvo = curva[curva["cobertura_media"] >= 0.90]
    L = int(alvo["lag_semanas"].iloc[0]) if not alvo.empty else 8
    print(f"\n→ **L as-of sugerido (cobertura média ≥90%): {L} semanas**\n")

    # 2 — fronteiras e folds anuais
    prof, woy_fron, folds_a = folds_anuais(df, seq, widx)
    print("## 2. Perfil sazonal (média municipal por week-of-year, 2024–25)\n")
    print(f"Pico ≈ W{int(prof.idxmax())}; fronteira de ano epidêmico derivada ≈ "
          f"**W{woy_fron}** (vale de transmissão). Recomputar quando SINAN 2016+ "
          "(US04) chegar.\n")
    print(md_table(pd.DataFrame(folds_a)[["caminho", "origem", "i_train_max",
                                          "i_test_min", "i_test_max"]]))
    print("\n### Métricas por fold anual\n")
    for f in folds_a:
        rows = avaliar_fold(df, f, casos_map)
        if rows:
            t = pd.DataFrame(rows)
            t.insert(0, "fold", f'{f["caminho"]} @ {f["origem"]}')
            print(md_table(t))
            print()

    # 3 — rolling-origin nível 2
    folds2 = folds_step(seq)
    res2 = avaliar_step(df, folds2, casos_map)
    print(f"## 3. Rolling-origin nível 2 — {len(folds2)} origens, passo de "
          f"{PASSO} semanas, expanding window com purge\n")
    print(md_table(res2[["origem", "h", "n_teste", "mae_xgb", "mae_persist",
                         "mae_sazonal", "skill_vs_persist",
                         f"p{K}_xgb", f"p{K}_persist"]]))
    print("\n### Agregado por horizonte (nível 2)\n")
    res2["bat_persist"] = res2["skill_vs_persist"] < 1
    res2["bat_sazonal"] = res2["mae_xgb"] < res2["mae_sazonal"]
    agg = res2.groupby("h").agg(
        n_folds=("origem", "nunique"),
        mae_xgb_medio=("mae_xgb", "mean"),
        skill_medio=("skill_vs_persist", "mean"),
        skill_min=("skill_vs_persist", "min"),
        pct_folds_acima_persist=("bat_persist", "mean"),
        pct_folds_acima_sazonal=("bat_sazonal", "mean"),
    ).round(3).reset_index()
    agg["pct_folds_acima_persist"] = (agg["pct_folds_acima_persist"] * 100).round(1)
    agg["pct_folds_acima_sazonal"] = (agg["pct_folds_acima_sazonal"] * 100).round(1)
    print(md_table(agg))

    # 4 — demonstrativo de vazamento
    print("\n## 4. Inflação de métricas: KFold aleatório (70/30) vs divisão temporal\n")
    print(md_table(demo_vazamento(df, seq, casos_map)))

    print(f"\n## 5. Parâmetros do esquema → insumo US26: L={L} semanas; "
          f"fronteira B=W{woy_fron}; nível 2: {len(folds2)} origens × passo {PASSO}.")


if __name__ == "__main__":
    main()
