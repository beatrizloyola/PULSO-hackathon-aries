import json
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import xgboost as xgb

from app import config

_model: Optional[xgb.XGBRegressor] = None
_feature_cols = [
    "tendencia_epidemiologica",
    "condicoes_climaticas",
    "focos_identificados",
    "vulnerabilidade_territorial",
    "historico",
    "vizinhos_semana_passada",
    "semana_ano",
    "ds_encoded",
]


def load_model() -> xgb.XGBRegressor:
    global _model
    if _model is not None:
        return _model

    if config.MODEL_FILE.exists():
        print(f"[model] Carregando modelo de {config.MODEL_FILE}")
        _model = xgb.XGBRegressor()
        _model.load_model(str(config.MODEL_FILE))
    else:
        print("[model] Modelo não encontrado. Treinando com dados sintéticos...")
        _train_from_synthetic()
    return _model


def _train_from_synthetic():
    import pandas as pd
    from sklearn.model_selection import train_test_split

    df = pd.read_csv(config.TRAINING_DATA_FILE)
    X = df[_feature_cols]
    y = df["target_prioridade"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    global _model
    _model = xgb.XGBRegressor(**config.XGB_PARAMS)
    _model.fit(X_train, y_train)
    _model.save_model(str(config.MODEL_FILE))
    print("[model] Modelo treinado e salvo.")


def predict_scores(df_features: pd.DataFrame) -> np.ndarray:
    model = load_model()
    X = df_features[_feature_cols]
    preds = model.predict(X)
    # Clamp 0-100
    return np.clip(np.round(preds), 0, 100)


def explain_prediction(bairro_id: str, df_features: pd.DataFrame) -> dict:
    """
    Retorna decomposição da predição por feature usando pred_contribs do XGBoost.
    """
    model = load_model()
    row = df_features[df_features["bairro_id"] == bairro_id]
    if row.empty:
        return {"error": "Bairro não encontrado"}

    X = row[_feature_cols]
    # pred_contribs retorna [base_value, feat1_contrib, ..., featN_contrib]
    contribs = model.predict(X, pred_contribs=True)
    base_value = float(contribs[0][0])
    feature_contribs = contribs[0][1:].tolist()

    total = base_value + sum(feature_contribs)
    contributions = []
    for feat, val in zip(_feature_cols, feature_contribs):
        contributions.append({
            "feature": feat,
            "contribuicao": round(float(val), 2),
            "contribuicao_percentual": round((float(val) / total * 100) if total != 0 else 0, 1),
        })

    return {
        "bairro_id": bairro_id,
        "base_value": round(base_value, 2),
        "predicao_final": round(float(total), 1),
        "contribuicoes": contributions,
    }


def classificar_prioridade(score: float):
    if score >= 85:
        return {"rotulo": "Crítico", "chave": "critico"}
    if score >= 70:
        return {"rotulo": "Alto", "chave": "alto"}
    if score >= 50:
        return {"rotulo": "Moderado", "chave": "moderado"}
    return {"rotulo": "Baixo", "chave": "baixo"}


# ============================================================
# Previsão de casos (forecast) — modelos por horizonte
# ============================================================

_forecast_models: dict = {}

# Meia-saturação do mapa casos previstos -> score 0-100. Com este valor,
# ~5 casos/semana => 50 (Moderado), ~12 => 70 (Alto), ~28 => 85 (Crítico).
# Monotônico em casos e comparável entre semanas (score absoluto, não relativo).
CASOS_MEIA_SATURACAO = 5.0


def load_forecast_model(horizon: int) -> xgb.XGBRegressor:
    if horizon in _forecast_models:
        return _forecast_models[horizon]
    path = config.forecast_model_file(horizon)
    if not path.exists():
        raise FileNotFoundError(
            f"Modelo de forecast h={horizon} não encontrado em {path}. "
            f"Rode: python -m scripts.train_forecast")
    m = xgb.XGBRegressor()
    m.load_model(str(path))
    _forecast_models[horizon] = m
    return m


def predict_casos(df_features: pd.DataFrame, horizon: int = 1) -> np.ndarray:
    """Prevê casos por bairro em t+horizon a partir das features de forecast."""
    from app.services import forecast_features as ff
    model = load_forecast_model(horizon)
    preds = model.predict(df_features[ff.FEATURES])
    return np.clip(preds, 0, None)


def casos_para_score(casos) -> np.ndarray:
    """Mapeia casos previstos -> score 0-100 (saturação suave, monotônica)."""
    casos = np.asarray(casos, dtype=float)
    return np.clip(100.0 * casos / (casos + CASOS_MEIA_SATURACAO), 0, 100)


def explain_forecast(bairro_id, panel: pd.DataFrame, horizon: int = 1) -> dict:
    """Contribuições do mesmo modelo Poisson e dados APAC usados no ranking."""
    from app.services.forecast_features import FEATURES
    row = panel[panel["bairro_id"] == bairro_id]
    if row.empty:
        return {"error": "Bairro não encontrado"}
    model = load_forecast_model(horizon)
    matrix = xgb.DMatrix(row[FEATURES])
    values = model.get_booster().predict(matrix, pred_contribs=True)[0]
    cases = float(model.predict(row[FEATURES])[0])
    return {
        "bairro_id": bairro_id, "horizonte": horizon,
        "base_value": float(values[-1]),
        "escala_contribuicoes": "log(casos); exp(base_value + soma das contribuições) = casos previstos",
        "casos_previstos": round(cases, 1),
        "predicao_final": round(cases, 1),
        "score": round(float(casos_para_score(cases))),
        "contribuicoes": [{"feature": feature, "contribuicao": float(value)}
                          for feature, value in zip(FEATURES, values[:-1])],
    }
