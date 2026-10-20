"""
Modelo servido pela API: o pipeline pyfunc exportado de um run do MLflow para
app/models/pulso_forecast (scripts/train_forecast.py + scripts/export_model.py).
"""
from typing import Optional

import mlflow.pyfunc
import pandas as pd

from app import config
from app.services.forecaster import PulsoForecaster

_pyfunc: Optional[mlflow.pyfunc.PyFuncModel] = None


def load_forecaster() -> mlflow.pyfunc.PyFuncModel:
    global _pyfunc
    if _pyfunc is None:
        if not (config.FORECAST_MODEL_DIR / "MLmodel").exists():
            raise FileNotFoundError(
                f"Modelo não encontrado em {config.FORECAST_MODEL_DIR}. Rode: "
                "python scripts/train_forecast.py && python scripts/export_model.py")
        _pyfunc = mlflow.pyfunc.load_model(str(config.FORECAST_MODEL_DIR))
    return _pyfunc


def _forecaster() -> PulsoForecaster:
    return load_forecaster().unwrap_python_model()


def model_run_id() -> str:
    return load_forecaster().metadata.run_id


def prever(df_features: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """DataFrame [casos_previstos, score] alinhado ao índice de df_features."""
    cols = _forecaster().features
    X = df_features[cols].astype("float64")
    return load_forecaster().predict(X, params={"horizonte": horizon})


def explicar(row: pd.DataFrame, horizon: int = 1) -> dict:
    return _forecaster().explain(row, horizon)


def classificar_prioridade(score: float):
    if score >= 85:
        return {"rotulo": "Crítico", "chave": "critico"}
    if score >= 70:
        return {"rotulo": "Alto", "chave": "alto"}
    if score >= 50:
        return {"rotulo": "Moderado", "chave": "moderado"}
    return {"rotulo": "Baixo", "chave": "baixo"}
