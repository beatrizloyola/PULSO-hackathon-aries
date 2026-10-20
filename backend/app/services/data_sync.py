"""Coleta periódica e publicação atômica de snapshots APAC/SINAN/temperatura.

Falhas preservam o snapshot anterior. Nenhuma chuva ausente é imputada como zero.
"""
from datetime import date, datetime, timedelta
from io import StringIO
import fcntl
import hashlib
import json
import logging
import re
import threading
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo

from epiweeks import Week
import pandas as pd
import requests

from app import config
from app.services import apac_client

log = logging.getLogger(__name__)
TZ = ZoneInfo("America/Recife")


def today():
    return datetime.now(TZ).date()


def epiweek(dt):
    w = Week.fromdate(dt, system="cdc")
    return w.year * 100 + w.week


def norm(value):
    return "".join(c for c in unicodedata.normalize("NFD", str(value).strip().upper())
                   if unicodedata.category(c) != "Mn")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def atomic_json(path, value):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def normalize_sinan(df):
    required = {"NM_BAIRRO", "DT_NOTIFIC", "ID_MUNICIP"}
    if not required.issubset(df.columns):
        raise ValueError("SINAN: colunas de bairro, município ou data ausentes")
    df = df.copy()
    municipality = df["ID_MUNICIP"].astype(str).str.replace(r"\.0$", "", regex=True)
    df = df[municipality.isin(["261160", "2611606"])]
    dates = pd.to_datetime(df["DT_NOTIFIC"], format="%d/%m/%Y", errors="coerce")
    if dates.isna().any() or df.empty:
        raise ValueError("SINAN: datas inválidas ou nenhuma notificação de Recife")
    if (dates.dt.date > today()).any():
        raise ValueError("SINAN: notificação com data futura")
    df["semana"] = dates.apply(lambda x: epiweek(x.date()))
    df["bairro_norm"] = df["NM_BAIRRO"].fillna("").apply(norm)
    cases = df.groupby(["bairro_norm", "semana"]).size().reset_index(name="casos")
    return cases, dates.min().date(), dates.max().date()


def complete_case_weeks(periods):
    """Só semanas fechadas até a última notificação; cobertura não é completude SINAN."""
    days = set()
    for start, end in periods:
        days.update(pd.date_range(start, min(end, today() - timedelta(days=1))).date)
    counts = {}
    for dt in days:
        code = epiweek(dt)
        counts[code] = counts.get(code, 0) + 1
    return sorted(code for code, count in counts.items() if count == 7)


def aggregate_weather(readings, temperatures):
    daily = readings.groupby("data", as_index=False).agg(
        chuva_mm=("chuva_mm", "mean"), n_est=("estacao", "nunique"))
    daily = daily.merge(temperatures, on="data", how="outer", validate="one_to_one")
    daily["semana"] = pd.to_datetime(daily["data"]).apply(lambda x: epiweek(x.date()))
    daily["dia_valido"] = daily[["chuva_mm", "temp_media", "temp_max"]].notna().all(axis=1).astype(int)
    weekly = daily.groupby("semana", as_index=False).agg(
        chuva_mm=("chuva_mm", lambda x: x.sum(min_count=7)),
        temp_media=("temp_media", "mean"), temp_max=("temp_max", "mean"),
        dias=("dia_valido", "sum"), n_est=("n_est", "mean"))
    weekly.loc[weekly["dias"] != 7, ["chuva_mm", "temp_media", "temp_max"]] = float("nan")
    return weekly


def eligible_weeks(weather, case_weeks):
    """Semana de referência e quatro anteriores, sem saltar lacunas."""
    complete = set(case_weeks).intersection(weather.loc[weather.dias == 7, "semana"])
    eligible = []
    for code in sorted(complete):
        week = Week(code // 100, code % 100, system="cdc")
        previous = [week - n for n in range(5)]
        if all(w.year * 100 + w.week in complete for w in previous):
            eligible.append(code)
    return eligible


def download_temperatures(session, start, end):
    response = session.get(config.OPENMETEO_ARCHIVE_URL, params={
        "latitude": config.RECIFE_LAT, "longitude": config.RECIFE_LON,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_mean,temperature_2m_max", "timezone": "America/Recife",
    }, timeout=(10, 60))
    response.raise_for_status()
    payload = response.json()
    daily = payload["daily"]
    df = pd.DataFrame({"data": daily["time"], "temp_media": daily["temperature_2m_mean"],
                       "temp_max": daily["temperature_2m_max"]})
    expected = pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
    if df.empty or df["data"].tolist() != expected:
        raise ValueError("Temperatura: período retornado não corresponde ao solicitado")
    for col in ("temp_media", "temp_max"):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not df[col].dropna().between(-20, 60).all():
            raise ValueError("Temperatura: valor fora do intervalo válido")
    return df, payload


def discover_resources(package):
    resources = {}
    for resource in package.get("resources", []):
        name = resource.get("name", "")
        match = re.search(r"\b(20\d{2})\b", name)
        if (resource.get("format", "").upper() == "CSV" and "dengue" in name.lower()
                and match and config.DATA_START_YEAR <= int(match[1]) <= today().year):
            year = int(match[1])
            if year in resources:
                raise ValueError(f"SINAN: mais de um CSV de dengue para {year}")
            resources[year] = resource
    if not resources:
        raise ValueError("SINAN: catálogo não contém CSVs de dengue no período")
    return resources


def sync_data(force=False):
    config.SYNC_DIR.mkdir(parents=True, exist_ok=True)
    with (config.SYNC_DIR / "sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "em_andamento"}
        current = read_json(config.SYNC_DIR / "current.json")
        now = datetime.now(TZ)
        if current and not force:
            age = (now - datetime.fromisoformat(current["coletado_em"])).total_seconds()
            if age < config.DATA_REFRESH_SECONDS:
                return current
        snapshot_id = now.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        folder = config.SYNC_DIR / snapshot_id
        folder.mkdir()
        try:
            with requests.Session() as session:
                session.headers["User-Agent"] = "PULSO/1.0 (pesquisa; dados publicos Recife)"
                response = session.get(f"{config.CKAN_API_URL}/action/package_show",
                                       params={"id": config.DATASET_DENGUE_ID}, timeout=(10, 30))
                response.raise_for_status()
                catalog = response.json()
                if not catalog.get("success"):
                    raise ValueError("SINAN: consulta CKAN sem sucesso")
                resources = discover_resources(catalog["result"])
                cases, periods, provenance = [], [], []
                for year, resource in sorted(resources.items()):
                    log.info("SINAN: coletando %s", year)
                    response = session.get(resource["url"], timeout=(10, 90))
                    response.raise_for_status()
                    raw = pd.read_csv(StringIO(response.content.decode("utf-8-sig")),
                                      sep=";", low_memory=False)
                    grouped, first, last = normalize_sinan(raw)
                    cases.append(grouped)
                    periods.append((date(year, 1, 1), min(last, date(year, 12, 31))))
                    provenance.append({"ano": year, "url": resource["url"],
                                       "modificado_em": resource.get("last_modified"),
                                       "sha256": hashlib.sha256(response.content).hexdigest(),
                                       "primeira_notificacao": str(first), "ultima_notificacao": str(last)})
                cases = pd.concat(cases).groupby(["bairro_norm", "semana"], as_index=False)["casos"].sum()
                all_readings, all_temps, apac_sources = [], [], []
                end = today() - timedelta(days=1)
                for year in range(config.DATA_START_YEAR, end.year + 1):
                    start, stop = date(year, 1, 1), min(date(year, 12, 31), end)
                    log.info("APAC: coletando %s a %s", start, stop)
                    readings, html = apac_client.download_diario(session, start, stop)
                    (folder / f"apac_{year}.html").write_text(html, encoding="utf-8")
                    all_readings.append(readings)
                    temps, payload = download_temperatures(session, start, stop)
                    (folder / f"temperatura_{year}.json").write_text(json.dumps(payload), encoding="utf-8")
                    all_temps.append(temps)
                    apac_sources.append({"inicio": str(start), "fim": str(stop),
                                         "sha256": hashlib.sha256(html.encode()).hexdigest()})
                readings = pd.concat(all_readings, ignore_index=True)
                temps = pd.concat(all_temps, ignore_index=True)
                weather = aggregate_weather(readings, temps)
                weeks = complete_case_weeks(periods)
                available = eligible_weeks(weather, weeks)
                if not available:
                    raise ValueError("Não há cinco semanas consecutivas completas nas fontes")
                if max(available) < current.get("ultima_semana_comum", 0):
                    raise ValueError("A nova coleta reduziria a cobertura; preservando o snapshot anterior")
                cases.to_csv(folder / "casos.csv", index=False)
                weather.to_csv(folder / "clima.csv", index=False)
                readings.to_csv(folder / "leituras_apac.csv", index=False)
                metadata = {
                    "schema": 1, "snapshot": snapshot_id, "coletado_em": now.isoformat(),
                    "anos_casos": sorted(resources), "semanas_casos": weeks,
                    "ultima_semana_comum": max(available),
                    "casos_ate": str(max(end for _, end in periods)),
                    "chuva_ate": str(readings["data"].max()),
                    "temperatura_ate": str(temps.dropna()["data"].max()),
                    "fonte_chuva": config.APAC_PORTAL_URL,
                    "consulta_chuva": config.APAC_HISTORICO_DIARIO_URL,
                    "metodo_chuva": "média diária das estações de Recife; soma semanal CDC",
                    "recursos_sinan": provenance, "consultas_apac": apac_sources,
                }
                atomic_json(folder / "metadata.json", metadata)
                atomic_json(config.SYNC_DIR / "current.json", metadata)
                atomic_json(config.SYNC_DIR / "attempt.json", {"tentativa_em": now.isoformat(), "erro": None})
                return metadata
        except Exception as exc:
            atomic_json(config.SYNC_DIR / "attempt.json", {
                "tentativa_em": now.isoformat(), "erro": str(exc)[:500]})
            log.exception("Coleta falhou; mantendo os últimos dados válidos")
            raise


def load_snapshot():
    meta = read_json(config.SYNC_DIR / "current.json")
    if not meta:
        return None
    folder = config.SYNC_DIR / meta["snapshot"]
    return pd.read_csv(folder / "casos.csv"), pd.read_csv(folder / "clima.csv"), meta


def data_status(reference, meta=None):
    meta = read_json(config.SYNC_DIR / "current.json") if meta is None else meta
    attempt = read_json(config.SYNC_DIR / "attempt.json")
    reasons = []
    collected = meta.get("coletado_em")
    if not collected:
        reasons.append("Usando histórico local; coleta online ainda não concluída.")
    elif (datetime.now(TZ) - datetime.fromisoformat(collected)).total_seconds() > config.DATA_REFRESH_SECONDS * 2:
        reasons.append("A coleta das fontes está atrasada.")
    if attempt.get("erro"):
        reasons.append("Última coleta falhou; preservados os últimos dados válidos.")
    ref_end = Week(reference // 100, reference % 100, system="cdc").enddate()
    if (today() - ref_end).days > 21:
        reasons.append("Histórico disponível não cobre as últimas semanas; a previsão se refere ao período exibido.")
    return {"fonte_chuva": config.APAC_PORTAL_URL, "fonte_temperatura": "Open-Meteo archive",
            "fonte_casos": "SINAN / Dados Abertos do Recife", "coletado_em": collected,
            "chuva_ate": meta.get("chuva_ate"), "casos_ate": meta.get("casos_ate"),
            "desatualizados": bool(reasons), "avisos": reasons,
            "ultima_tentativa": attempt.get("tentativa_em")}


def start_background_sync():
    def run():
        while True:
            try:
                sync_data()
            except Exception:
                pass  # O erro e a tentativa ficam registrados para a API.
            threading.Event().wait(min(config.DATA_REFRESH_SECONDS, 3600))
    if config.AUTO_SYNC:
        threading.Thread(target=run, name="pulso-data-sync", daemon=True).start()
