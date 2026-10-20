# PULSO Backend

API **Flask** com XGBoost + MLflow para previsão de casos de dengue e priorização
dos 94 bairros de Recife. Usa chuva do portal APAC, temperatura histórica do
Open-Meteo e notificações SINAN do catálogo de Dados Abertos do Recife.

## Stack

- **Flask** — API REST
- **XGBoost** — previsão de casos de dengue por bairro (horizontes de 1–4 semanas)
- **MLflow** — tracking de treinos e empacotamento do modelo (pyfunc/cloudpickle)
- **Pandas** — painel bairro × semana epidemiológica

## Executar (Linux, Python 3.12)

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main        # http://localhost:8000
```

O modelo servido já vem no repositório (`app/models/pulso_forecast`). A coleta
de dados é iniciada em segundo plano e renovada diariamente por padrão. A API
continua usando o último conjunto válido enquanto a coleta acontece.
Configuração, metodologia e testes em [DADOS_APAC.md](DADOS_APAC.md).

Atualizar os dados não retreina o modelo: para promover um modelo treinado com
os dados novos, siga a seção abaixo.

## Treinar e promover um modelo

```bash
python scripts/train_forecast.py   # loga um run no MLflow
python scripts/export_model.py     # gate de métricas + export do último run
python scripts/export_model.py --run-id <RUN_ID>   # ou um run específico
pytest -q
mlflow ui --backend-store-uri sqlite:///mlflow.db  # comparar runs
```

- O export só acontece se o XGBoost bater a persistência (MAE menor e
  precisão@10 ≥) em todos os horizontes; caso contrário sai com código 1.
- Commite `app/models/pulso_forecast/` e `app/models/forecast_meta.json` para
  promover o modelo. `mlflow.db` e `mlruns/` são locais (gitignored).
- `python_model.pkl` é um pickle: só carregue artefatos de origem confiável. Ele
  fica preso às versões de `requirements.txt` do modelo exportado e referencia
  `app.services.forecaster`, então renomear essa classe exige retreinar.

## CI (GitHub Actions)

`.github/workflows/ml.yml` roda em PR/push que toca `backend/`: treina, aplica
o gate, exporta, roda `pytest` e publica o modelo e o tracking como artefato.
Para enviar os runs a um servidor MLflow do time, configure os secrets
`MLFLOW_TRACKING_URI` (e, se houver autenticação, `MLFLOW_TRACKING_USERNAME`
/ `MLFLOW_TRACKING_PASSWORD`). Sem eles, o tracking é local ao job.

## Endpoints

| Método | Rota | Conteúdo |
|---|---|---|
| GET | `/health` | Status + `run_id` do modelo servido |
| GET | `/bairros` | Bairros, distrito, RPA e ZEIS |
| POST | `/prioridade` | Ranking, semanas disponíveis, fontes, data da coleta e avisos (`semana_id`, `horizonte`, `top_n`, `capacidade`) |
| GET | `/prioridade/<bairro_id>` | Detalhe de bairro (`?semana_id=&horizonte=`) |
| GET | `/mapa` | GeoJSON com o mesmo ranking |
| POST | `/prioridade/explicacao` | Contribuições SHAP da previsão, em escala log(casos) (`bairro_id`, `semana_id`, `horizonte`) |

Em `/prioridade`, omita `semana_id` para a última semana com dados suficientes.
Informe `YYYY-Wnn` para consultar outra semana retornada em `semanas_disponiveis`.
`horizonte` aceita 1 a 4. Semana sem cobertura retorna HTTP 400; ausência de um
histórico suficiente retorna HTTP 503.

## Variáveis de ambiente

```bash
MLFLOW_TRACKING_URI=sqlite:///mlflow.db   # padrão: backend/mlflow.db
MLFLOW_EXPERIMENT=pulso-forecast
```

Variáveis da coleta de dados (`AUTO_SYNC`, `DATA_REFRESH_SECONDS`, …) em
[DADOS_APAC.md](DADOS_APAC.md).
