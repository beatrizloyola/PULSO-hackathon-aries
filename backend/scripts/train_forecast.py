"""
Treina o pipeline de previsão de casos e registra o run no MLflow.

Para cada horizonte h: backtest out-of-time (métricas honestas vs. baseline de
persistência) e depois modelo final em todo o histórico. Os modelos finais são
empacotados num único PulsoForecaster (pyfunc/cloudpickle) logado no run.
Para servir, exporte o run: python scripts/export_model.py
"""
import os
import subprocess
import sys
from pathlib import Path

import mlflow
import numpy as np
import xgboost as xgb
from mlflow.models import infer_signature
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.services import forecast_features as ff
from app.services.forecaster import PulsoForecaster
from app.services.tracking import init_tracking

MODEL_NAME = "pulso-forecast"
FONTE_CLIMA = "APAC (chuva) + Open-Meteo (temperatura)"


def _precision_at_k(test, pred_col, truth_col, k):
    precs = []
    for _, grp in test.groupby("semana"):
        if grp[truth_col].sum() == 0:
            continue
        top_pred = set(grp.nlargest(k, pred_col)["bairro"])
        top_true = set(grp.nlargest(k, truth_col)["bairro"])
        precs.append(len(top_pred & top_true) / k)
    return round(float(np.mean(precs)), 4) if precs else None


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=config.BASE_DIR, capture_output=True,
                          text=True, check=True).stdout.strip()


def _run_name() -> str:
    """ci-pr9-abc1234 | ci-main-abc1234 | local-abc1234[-dirty]"""
    if os.getenv("GITHUB_ACTIONS"):
        ref = os.environ["GITHUB_REF"]  # refs/pull/9/merge | refs/heads/main
        if ref.startswith("refs/pull/"):
            origem = f"ci-pr{ref.split('/')[2]}"
        else:
            origem = "ci-" + ref.removeprefix("refs/heads/").replace("/", "-")
        return f"{origem}-{os.environ['GITHUB_SHA'][:7]}"
    try:
        sha = _git("rev-parse", "--short=7", "HEAD")
        dirty = _git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "local"
    return f"local-{sha}" + ("-dirty" if dirty else "")


def main():
    init_tracking()
    cutoff, k = config.FORECAST_BACKTEST_CUTOFF, config.FORECAST_TOP_K

    print("[train_forecast] Construindo painel (SINAN real + APAC)...")
    panel = ff.build_panel(config.FORECAST_ANOS)
    df = ff.add_targets(ff.add_features(panel), config.FORECAST_HORIZONS)
    widx = {cod: i for i, cod in enumerate(ff.semana_seq(config.FORECAST_ANOS))}
    df["widx"] = df["semana"].map(widx)
    cutoff_idx = widx[cutoff]
    print(f"   Painel: {df['bairro'].nunique()} bairros x {df['semana'].nunique()} semanas")

    with mlflow.start_run(run_name=_run_name()) as run:
        mlflow.log_params({
            **config.FORECAST_XGB_PARAMS,
            "anos_treino": config.FORECAST_ANOS,
            "horizontes": config.FORECAST_HORIZONS,
            "backtest_cutoff": cutoff,
            "top_k": k,
            "casos_meia_saturacao": config.CASOS_MEIA_SATURACAO,
            "n_features": len(ff.FEATURES),
        })
        mlflow.set_tags({
            "origem": "ci" if os.getenv("GITHUB_ACTIONS") else "local",
            "fonte_casos": "SINAN (cache)",
            "fonte_clima": FONTE_CLIMA,
        })
        targets = [f"y_h{h}" for h in config.FORECAST_HORIZONS]
        anos = "-".join(map(str, config.FORECAST_ANOS))
        mlflow.log_input(mlflow.data.from_pandas(
            df[["bairro_id", "semana", *ff.FEATURES, *targets]],
            name=f"painel-sinan-apac-{anos}",
        ), context="training")
        if os.getenv("GITHUB_ACTIONS"):
            mlflow.set_tags({
                "github.run_url": f"{os.environ['GITHUB_SERVER_URL']}/"
                                  f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
                                  f"{os.environ['GITHUB_RUN_ID']}",
                "github.ref": os.environ["GITHUB_REF"],
                "github.sha": os.environ["GITHUB_SHA"],
            })

        metrics, finals = {}, {}
        for h in config.FORECAST_HORIZONS:
            y = f"y_h{h}"
            d = df.dropna(subset=ff.FEATURES + [y]).copy()

            # --- backtest out-of-time (métrica honesta) ---
            train = d[d["widx"] + h <= cutoff_idx]
            test = d[d["widx"] > cutoff_idx].copy()
            if train.empty or test.empty:
                raise ValueError(f"Histórico insuficiente para treinar/validar horizonte {h}")
            m = xgb.XGBRegressor(**config.FORECAST_XGB_PARAMS)
            m.fit(train[ff.FEATURES], train[y])
            test["pred"] = np.clip(m.predict(test[ff.FEATURES]), 0, None)
            test["persist"] = test["casos"]
            mh = {
                "mae_xgb": round(float(mean_absolute_error(test[y], test["pred"])), 4),
                "mae_persistencia": round(float(mean_absolute_error(test[y], test["persist"])), 4),
                "precisao_k_xgb": _precision_at_k(test, "pred", y, k),
                "precisao_k_persistencia": _precision_at_k(test, "persist", y, k),
                "n_treino_backtest": int(len(train)),
                "n_teste": int(len(test)),
            }
            metrics[f"h{h}"] = mh
            mlflow.log_metrics({f"h{h}_{name}": v for name, v in mh.items() if v is not None})

            # --- modelo final: TODO o histórico com alvo válido ---
            final = xgb.XGBRegressor(**config.FORECAST_XGB_PARAMS)
            final.fit(d[ff.FEATURES], d[y])
            finals[h] = final
            print(f"   h={h}: MAE {mh['mae_xgb']} vs persist {mh['mae_persistencia']} | "
                  f"P@{k} {mh['precisao_k_xgb']} vs {mh['precisao_k_persistencia']}")

        forecaster = PulsoForecaster(finals, ff.FEATURES, config.CASOS_MEIA_SATURACAO)
        example = df.dropna(subset=ff.FEATURES)[ff.FEATURES].head(5).astype("float64")
        signature = infer_signature(example, forecaster.predict(None, example),
                                    params={"horizonte": 1})
        info = mlflow.pyfunc.log_model(
            name=MODEL_NAME,
            python_model=forecaster,
            signature=signature,
            input_example=example,
        )
        mlflow.set_tag("model_uri", info.model_uri)
        mlflow.log_dict({
            "run_id": run.info.run_id,
            "model_uri": info.model_uri,
            "features": ff.FEATURES,
            "horizontes": config.FORECAST_HORIZONS,
            "anos_treino": config.FORECAST_ANOS,
            "params": config.FORECAST_XGB_PARAMS,
            "casos_meia_saturacao": config.CASOS_MEIA_SATURACAO,
            "backtest": {"cutoff": cutoff, "k": k, "metrics": metrics},
            "fontes": {"casos": "SINAN (cache)", "clima": FONTE_CLIMA},
            "dados_treino": panel.attrs.get("snapshot_meta", {}),
        }, "forecast_meta.json")

    print(f"[train_forecast] run_id={run.info.run_id} model_uri={info.model_uri}")


if __name__ == "__main__":
    main()
