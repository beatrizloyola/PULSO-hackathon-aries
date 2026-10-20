from typing import Optional, Tuple

import numpy as np
import pandas as pd
from epiweeks import Week

from app import config
from app.services import forecast_features as ff, data_sync
from app.services import model as model_svc

_featured_panel: Optional[pd.DataFrame] = None
_panel_signature = None


class DadosIndisponiveis(RuntimeError):
    pass


def _clamp(v, lo=0.0, hi=100.0):
    return np.clip(v, lo, hi)


def _semana_alvo(semana_cod: int, horizon: int) -> int:
    """Código YYYYWW da semana-alvo (referência + horizon), com virada de ano."""
    ano, sem = divmod(semana_cod, 100)
    w = Week(ano, sem, system="cdc") + horizon
    return w.year * 100 + w.week


def get_featured_panel() -> pd.DataFrame:
    """Recarrega quando a coleta publica um snapshot ou muda o cache local."""
    global _featured_panel, _panel_signature
    files = [config.SYNC_DIR / "current.json", config.BAIRROS_LOOKUP_FILE]
    files += sorted(config.CACHE_DIR.glob("apac_clima_semana_*.csv"))
    files += sorted(config.CACHE_DIR.glob("dengue_*.csv"))
    signature = tuple((str(p), p.stat().st_mtime_ns) for p in files if p.exists())
    if _featured_panel is None or signature != _panel_signature:
        panel = ff.add_features(ff.build_panel())
        valid = panel[ff.FEATURES].notna().all(axis=1)
        # Uma semana só pode compor o ranking se todos os bairros forem comparáveis.
        eligible = valid.groupby(panel["semana"]).all()
        panel = panel[panel["semana"].isin(eligible[eligible].index)]
        if panel.empty:
            raise DadosIndisponiveis("Não há semanas com dados completos e histórico suficiente para previsão.")
        _featured_panel, _panel_signature = panel, signature
    return _featured_panel


def _parse_semana(semana_id: Optional[str], panel: pd.DataFrame) -> int:
    """semana_id 'YYYY-Wnn' -> código YYYYWW; default = última semana disponível."""
    if semana_id and semana_id != "atual":
        try:
            ano, semana = map(int, semana_id.split("-W"))
            Week(ano, semana, system="cdc")
            cod = ano * 100 + semana
        except (ValueError, AttributeError):
            raise ValueError("Semana inválida; use YYYY-Wnn ou omita para a última disponível.") from None
        if cod not in panel["semana"].values:
            raise ValueError("Semana sem dados completos para previsão; escolha uma semana disponível.")
        return cod
    return int(panel["semana"].max())


def build_prioridades(semana_id: Optional[str] = None,
                      horizon: int = 1) -> Tuple[pd.DataFrame, dict]:
    """
    Retorna (df, meta). df tem uma linha por bairro com score, componentes e
    metadados (inclui casos_previstos). meta traz semana/horizonte resolvidos.
    """
    if horizon not in config.FORECAST_HORIZONS:
        raise ValueError("Horizonte deve estar entre 1 e 4 semanas.")
    panel = get_featured_panel()
    semana_cod = _parse_semana(semana_id, panel)

    cur = panel[panel["semana"] == semana_cod].copy()
    cur["bairro_nome"] = cur["bairro"]
    casos_prev = model_svc.predict_casos(cur, horizon=horizon).astype("float64")
    cur["casos_previstos"] = np.round(casos_prev, 1)
    cur["score"] = np.round(model_svc.casos_para_score(casos_prev)).astype(int)

    # --- componentes (explicabilidade) a partir de sinais REAIS ---
    roll = cur["roll4_mean"].fillna(cur["casos"]).clip(lower=0)
    cur["tendencia_epidemiologica"] = _clamp((cur["casos"] / (roll + 0.5)) * 50)
    chuva_ref = max(1.0, panel["chuva_mm"].mean())
    temp_norm = _clamp((cur["temp_media"] - 24) / (32 - 24) * 100)
    cur["condicoes_climaticas"] = _clamp(0.6 * (cur["chuva_roll4"].fillna(0) / (chuva_ref * 4)) * 100
                                         + 0.4 * temp_norm)
    # focos: sem fonte real de campo — proxy transparente por casos recentes
    cur["focos_identificados"] = _clamp((cur["casos"] / (roll + 0.5)) * 45 + 20)
    cur["vulnerabilidade_territorial"] = cur["vuln"]
    cur["historico"] = cur["hist"]

    # --- metadados ---
    cur["casos_semana_atual"] = cur["casos"].astype(int)
    cur["casos_semana_anterior"] = cur["casos_lag1"].fillna(0).astype(int)
    cur["focos_atuais"] = np.round(cur["focos_identificados"]).astype(int)
    cur["chuva_mm"] = cur["chuva_mm"].round(1)
    cur["temp_media"] = cur["temp_media"].round(1)
    cur["horizonte"] = horizon

    alvo_cod = _semana_alvo(semana_cod, horizon)
    meta = {
        "semana_cod": int(semana_cod),
        "semana_alvo_cod": int(alvo_cod),
        "horizonte": horizon,
        "fonte_casos": "SINAN (cache)",
        "fonte_clima": "APAC (chuva) + Open-Meteo (temperatura)",
        "semanas_disponiveis": sorted(int(w) for w in panel["semana"].unique()),
        "dados": data_sync.data_status(int(panel["semana"].max()), panel.attrs.get("snapshot_meta", {})),
    }
    return cur.reset_index(drop=True), meta
