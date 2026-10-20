import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "app" / "data"
MODELS_DIR = BASE_DIR / "app" / "models"
CACHE_DIR = DATA_DIR / "cache"

CKAN_BASE_URL = os.getenv("CKAN_BASE_URL", "https://dados.recife.pe.gov.br")
CKAN_API_URL = f"{CKAN_BASE_URL}/api/3"

INMET_BDMEP_URL = os.getenv("INMET_BDMEP_URL", "https://bdmep.inmet.gov.br/webservices")

# Temperatura histórica de apoio; chuva vem exclusivamente do portal APAC.
OPENMETEO_ARCHIVE_URL = os.getenv(
    "OPENMETEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive")
RECIFE_LAT = float(os.getenv("RECIFE_LAT", "-8.05"))
RECIFE_LON = float(os.getenv("RECIFE_LON", "-34.88"))

# APAC: fonte primária de chuva (Histórico Pluviométrico diário, Recife).
# http://dados.apac.pe.gov.br:41120/boletins/historico-pluviometrico/
APAC_HISTORICO_DIARIO_URL = os.getenv(
    "APAC_HISTORICO_DIARIO_URL",
    "http://dados.apac.pe.gov.br:41120/boletins/historico-pluviometrico/diario.php")
APAC_PORTAL_URL = "http://dados.apac.pe.gov.br:41120/dadosApac/"
SYNC_DIR = CACHE_DIR / "atualizacao"
DATA_REFRESH_SECONDS = max(60, int(os.getenv("DATA_REFRESH_SECONDS", "86400")))
AUTO_SYNC = os.getenv("AUTO_SYNC", "true").lower() == "true"
DATA_START_YEAR = int(os.getenv("DATA_START_YEAR", "2024"))

# Resource IDs CKAN (encontrados na pesquisa)
DATASET_DENGUE_ID = "3c990c15-29ad-46e5-8fd2-1b83289bb9f5"
DATASET_DISTRITOS_ID = "09ae25d3-7330-4fff-af57-9e9191a4c2f6"
DATASET_ZONEAMENTO_ID = "zoneamento"  # dataset slug

# Arquivos de referência
BAIRROS_LOOKUP_FILE = DATA_DIR / "bairros_lookup.json"
TRAINING_DATA_FILE = DATA_DIR / "training_data.csv"
MODEL_FILE = MODELS_DIR / "xgb_prioridade.json"

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL", "3600"))

# Configurações do modelo (legado — priorização por fórmula sintética)
XGB_PARAMS = {
    "n_estimators": 100,
    "max_depth": 4,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "random_state": 42,
}

# --- Previsão de casos (forecast) ---
FORECAST_HORIZONS = [1, 2, 3, 4]
FORECAST_ANOS = [2024, 2025]
FORECAST_META_FILE = MODELS_DIR / "forecast_meta.json"
# Objetivo count:poisson é apropriado para contagem de casos.
FORECAST_XGB_PARAMS = {
    "n_estimators": 300,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "count:poisson",
    "random_state": 42,
}


def forecast_model_file(h: int) -> Path:
    return MODELS_DIR / f"forecast_h{h}.json"
