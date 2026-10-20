import json
import sys
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.services import forecast_features as ff

# Semana de corte do backtest: treina alvo <= corte, testa depois (só 2025).
CUTOFF = 202520
K = 10  # capacidade de equipes para precisão@K


def _precision_at_k(test, pred_col, truth_col, k=K):
    precs = []
    for _, grp in test.groupby("semana"):
        if grp[truth_col].sum() == 0:
            continue
        top_pred = set(grp.nlargest(k, pred_col)["bairro"])
        top_true = set(grp.nlargest(k, truth_col)["bairro"])
        precs.append(len(top_pred & top_true) / k)
    return round(float(np.mean(precs)), 4) if precs else None


def main():
    print("[train_forecast] Construindo painel (SINAN real + APAC)...")
    panel = ff.build_panel(config.FORECAST_ANOS)
    df = ff.add_targets(ff.add_features(panel))
    widx = {cod: i for i, cod in enumerate(ff.semana_seq(config.FORECAST_ANOS))}
    df["widx"] = df["semana"].map(widx)
    cutoff_idx = widx[CUTOFF]
    print(f"   Painel: {df['bairro'].nunique()} bairros x {df['semana'].nunique()} semanas")

    metrics = {}
    for h in config.FORECAST_HORIZONS:
        y = f"y_h{h}"
        d = df.dropna(subset=ff.FEATURES + [y]).copy()

        # --- backtest out-of-time (para métrica honesta) ---
        train = d[d["widx"] + h <= cutoff_idx]
        test = d[d["widx"] > cutoff_idx].copy()
        if train.empty or test.empty:
            raise ValueError(f"Histórico insuficiente para treinar/validar horizonte {h}")
        m = xgb.XGBRegressor(**config.FORECAST_XGB_PARAMS)
        m.fit(train[ff.FEATURES], train[y])
        test["pred"] = np.clip(m.predict(test[ff.FEATURES]), 0, None)
        test["persist"] = test["casos"]
        metrics[f"h{h}"] = {
            "mae_xgb": round(float(mean_absolute_error(test[y], test["pred"])), 4),
            "mae_persistencia": round(float(mean_absolute_error(test[y], test["persist"])), 4),
            "precisao_k_xgb": _precision_at_k(test, "pred", y),
            "precisao_k_persistencia": _precision_at_k(test, "persist", y),
            "n_teste": int(len(test)),
        }

        # --- modelo final: treina em TODO o histórico com alvo válido ---
        final = xgb.XGBRegressor(**config.FORECAST_XGB_PARAMS)
        final.fit(d[ff.FEATURES], d[y])
        final.save_model(str(config.forecast_model_file(h)))
        print(f"   h={h}: MAE {metrics[f'h{h}']['mae_xgb']} vs persist "
              f"{metrics[f'h{h}']['mae_persistencia']} | "
              f"P@{K} {metrics[f'h{h}']['precisao_k_xgb']} vs "
              f"{metrics[f'h{h}']['precisao_k_persistencia']}  -> salvo")

    meta = {
        "features": ff.FEATURES,
        "horizontes": config.FORECAST_HORIZONS,
        "anos_treino": config.FORECAST_ANOS,
        "params": config.FORECAST_XGB_PARAMS,
        "backtest": {"cutoff": CUTOFF, "k": K, "metrics": metrics},
        "fontes": {"casos": "SINAN (cache)", "clima": "APAC (chuva) + Open-Meteo (temperatura)"},
        "dados_treino": panel.attrs.get("snapshot_meta", {}),
    }
    config.FORECAST_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.FORECAST_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[train_forecast] Metadados salvos em {config.FORECAST_META_FILE}")


if __name__ == "__main__":
    main()
