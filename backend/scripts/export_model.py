"""
Exporta um run do MLflow para app/models/ — é esse artefato que a API serve.

Gate de qualidade: o run só é exportado se, em TODOS os horizontes do backtest,
o XGBoost tiver MAE menor e precisão@K >= à da persistência (repetir os casos da
semana atual). Caso contrário sai com código 1 (falha o CI).

Uso:
    python scripts/export_model.py              # último run concluído
    python scripts/export_model.py --run-id ID  # run específico
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.services.tracking import init_tracking


def _latest_run_id(experiment_id: str) -> str:
    runs = mlflow.search_runs(
        experiment_ids=[experiment_id],
        filter_string="attributes.status = 'FINISHED' AND tags.model_uri != ''",
        order_by=["attributes.start_time DESC"],
        max_results=1,
        output_format="list",
    )
    if not runs:
        sys.exit(f"Nenhum run concluído em '{config.MLFLOW_EXPERIMENT}'. "
                 "Rode: python scripts/train_forecast.py")
    return runs[0].info.run_id


def gate(metrics: dict) -> list:
    """Lista de reprovações (vazia = aprovado)."""
    falhas = []
    for h, m in sorted(metrics.items()):
        if not m["mae_xgb"] < m["mae_persistencia"]:
            falhas.append(f"{h}: MAE {m['mae_xgb']} não é menor que persistência {m['mae_persistencia']}")
        pk, pk_base = m["precisao_k_xgb"], m["precisao_k_persistencia"]
        if pk is None or pk_base is None or pk < pk_base:
            falhas.append(f"{h}: P@K {pk} abaixo da persistência {pk_base}")
    return falhas


def _summary_markdown(meta: dict, falhas: list) -> str:
    k = meta["backtest"]["k"]
    linhas = [
        f"### Forecast — run `{meta['run_id']}`",
        "",
        f"| Horizonte | MAE XGB | MAE persistência | P@{k} XGB | P@{k} persistência |",
        "|---|---|---|---|---|",
    ]
    for h, m in sorted(meta["backtest"]["metrics"].items()):
        linhas.append(f"| {h} | {m['mae_xgb']} | {m['mae_persistencia']} | "
                      f"{m['precisao_k_xgb']} | {m['precisao_k_persistencia']} |")
    linhas.append("")
    linhas.append("**Gate: aprovado**" if not falhas else
                  "**Gate: reprovado**\n\n" + "\n".join(f"- {f}" for f in falhas))
    return "\n".join(linhas) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run-id", help="run do MLflow (padrão: último concluído)")
    args = parser.parse_args()

    experiment_id = init_tracking()
    run_id = args.run_id or _latest_run_id(experiment_id)
    meta = mlflow.artifacts.load_dict(f"runs:/{run_id}/forecast_meta.json")

    falhas = gate(meta["backtest"]["metrics"])
    client = mlflow.MlflowClient()
    client.set_tag(run_id, "gate", "reprovado" if falhas else "aprovado")
    resumo = _summary_markdown(meta, falhas)
    print(resumo)
    if summary_file := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(resumo)
    if falhas:
        sys.exit(1)

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.MODELS_DIR) as tmp:
        local = mlflow.artifacts.download_artifacts(artifact_uri=meta["model_uri"], dst_path=tmp)
        shutil.rmtree(config.FORECAST_MODEL_DIR, ignore_errors=True)
        shutil.move(local, config.FORECAST_MODEL_DIR)
    with open(config.FORECAST_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")

    client.set_tag(run_id, "exportado", "sim")
    print(f"[export_model] run {run_id} exportado para {config.FORECAST_MODEL_DIR}")


if __name__ == "__main__":
    main()
