"""
Pipeline de previsão de casos empacotado como modelo MLflow pyfunc.

O MLflow serializa a instância inteira com cloudpickle (python_model.pkl):
os boosters dos horizontes, a lista de features e o mapeamento casos -> score
viajam juntos. Treino e serving usam esta mesma classe, então features e
fórmula do score não divergem entre os dois lados.

Atenção: o pickle referencia esta classe pelo caminho do módulo
(app.services.forecaster) e fica preso às versões de xgboost/python do treino
(o MLflow grava requirements.txt e python_env.yaml junto do modelo).
Só carregue artefatos de origem confiável: abrir um pickle executa código.
"""
from typing import Dict, List

import mlflow.pyfunc
import numpy as np
import pandas as pd
import xgboost as xgb


class PulsoForecaster(mlflow.pyfunc.PythonModel):
    def __init__(self, models: Dict[int, xgb.XGBRegressor], features: List[str],
                 meia_saturacao: float):
        self.models = models
        self.features = list(features)
        self.meia_saturacao = float(meia_saturacao)

    @property
    def horizontes(self) -> List[int]:
        return sorted(self.models)

    def _model(self, horizon: int) -> xgb.XGBRegressor:
        if horizon not in self.models:
            raise ValueError(f"Horizonte {horizon} inválido; disponíveis: {self.horizontes}")
        return self.models[horizon]

    def predict_casos(self, df: pd.DataFrame, horizon: int) -> np.ndarray:
        """Casos previstos por linha em t+horizon."""
        preds = self._model(horizon).predict(df[self.features])
        return np.clip(preds, 0, None).astype("float64")

    def casos_para_score(self, casos) -> np.ndarray:
        """Score 0-100 absoluto (comparável entre semanas), monotônico em casos."""
        casos = np.asarray(casos, dtype=float)
        return np.clip(100.0 * casos / (casos + self.meia_saturacao), 0, 100)

    def predict(self, context, model_input, params=None):
        horizon = int((params or {}).get("horizonte", 1))
        casos = self.predict_casos(model_input, horizon)
        return pd.DataFrame(
            {"casos_previstos": casos, "score": self.casos_para_score(casos)},
            index=model_input.index,
        )

    def explain(self, row: pd.DataFrame, horizon: int) -> dict:
        """
        Decomposição SHAP (pred_contribs) de UMA linha. Com count:poisson as
        contribuições somam em escala log: exp(base_value + Σ contribuicao) =
        casos_previstos. efeito_multiplicativo = exp(contribuicao).
        """
        booster = self._model(horizon).get_booster()
        contribs = booster.predict(xgb.DMatrix(row[self.features]), pred_contribs=True)[0]
        feat_contribs, base_value = contribs[:-1], float(contribs[-1])
        total_abs = float(np.abs(feat_contribs).sum()) or 1.0
        itens = sorted(
            ({
                "feature": feat,
                "valor": float(row[feat].iloc[0]),
                "contribuicao": round(float(c), 4),
                "efeito_multiplicativo": round(float(np.exp(c)), 4),
                "contribuicao_percentual": round(float(c) / total_abs * 100, 1),
            } for feat, c in zip(self.features, feat_contribs)),
            key=lambda i: abs(i["contribuicao"]), reverse=True,
        )
        casos = float(np.exp(base_value + float(feat_contribs.sum())))
        return {
            "horizonte": horizon,
            "escala": "log(casos)",
            "base_value": round(base_value, 4),
            "casos_previstos": round(casos, 2),
            "score": round(float(self.casos_para_score(casos)), 1),
            "contribuicoes": itens,
        }
