#!/usr/bin/env python3
"""
Histórico SINAN 2016-2025 por bairro × semana epidemiológica (SE).

Gera a série de casos de dengue por bairro × SE
para Recife, a partir dos CSVs anuais do Portal de Dados Abertos do Recife
(CKAN, dataset "Casos de Dengue, Zika e Chikungunya").

saídas:
  backend/app/data/sinan_bairro_se_2016_2025.csv
      colunas: bairro, semana (YYYYWW), casos, ano
  backend/app/data/sinan_bairro_se_report.json
      % de registros sem bairro/geocodificação por ano + anos epidêmicos
"""
import json
import statistics
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config

ANOS = list(range(2016, 2026))
RECIFE_MUNICIP = "261160"
SENTINELAS_BAIRRO = {"", "NAN", "NONE", "IGNORADO", "NAO INFORMADO",
                     "NÃO INFORMADO", "DESCONHECIDO", "OUTROS"}


def _norm(s):
    if s is None:
        return None
    s = str(s).strip()
    if s.upper() in SENTINELAS_BAIRRO:
        return None
    out = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    out = out.upper().strip()
    return out if out else None


def _col(df, candidates):
    """Retorna a primeira coluna cujo nome contém algum candidato (prioridade na ordem dos candidatos)."""
    for cand in candidates:
        for c in df.columns:
            if cand in c.lower():
                return c
    return None


def _filtrar_municipio(df, mun_col, municip=RECIFE_MUNICIP):
    """Mantém apenas os registros do município de residência (padroniza a série)."""
    if mun_col is None:
        return df
    mask = df[mun_col].astype(str).str.contains(municip, na=False)
    return df[mask].copy()


def _filtrar_descartados(df, class_col):
    """Remove notificações descartadas (classificação final = 5)."""
    if class_col is None:
        return df
    return df[df[class_col].astype(str).str.strip() != "5"].copy()


def _reagregar(out_df):
    """Reagrega por (bairro, semana), soma casos e deriva o ano da semana (YYYYWW)."""
    out_df = out_df.copy()
    out_df["ano"] = out_df["semana"] // 100
    out_df = (
        out_df.groupby(["bairro", "semana"], as_index=False)
        .agg({"casos": "sum", "ano": "first"})
        .sort_values(["bairro", "semana"])
        .reset_index(drop=True)
    )
    return out_df[["bairro", "semana", "casos", "ano"]]


def _find_resource_url(pkg, year):
    for res in pkg.get("resources", []):
        name = (res.get("name") or "").lower()
        if "dengue" in name and str(year) in name:
            return res["url"]
    return None


def _download_year(year):
    cache = config.CACHE_DIR / f"dengue_{year}.csv"
    if cache.exists():
        return cache
    print(f"[{year}] baixando do CKAN...")
    r = requests.get(f"{config.CKAN_API_URL}/action/package_show",
                     params={"id": config.DATASET_DENGUE_ID}, timeout=60)
    r.raise_for_status()
    pkg = r.json()["result"]
    url = _find_resource_url(pkg, year)
    if not url:
        raise RuntimeError(f"recurso de dengue {year} não encontrado no CKAN")
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(resp.content)
    print(f"  -> {cache} ({len(resp.content)} bytes)")
    return cache


def _read_year(year):
    path = _download_year(year)
    for sep in (";", ","):
        try:
            df = pd.read_csv(path, sep=sep, encoding="utf-8", low_memory=False)
            if len(df.columns) > 5:
                return df
        except Exception:
            continue
    raise RuntimeError(f"não foi possível ler {path}")


def _canonical_bairros():
    lookup = json.loads((config.DATA_DIR / "bairros_lookup.json").read_text(encoding="utf-8"))
    canon = {}
    for b in lookup:
        canon[_norm(b["nome"])] = b["nome"]
    return canon


def main():
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    canon = _canonical_bairros()
    rows_out = []
    report = {"anos": {}}
    epidemic = []

    for year in ANOS:
        df = _read_year(year)
        n_total = len(df)

        # Filtro por município de RESIDÊNCIA em todos os anos (padroniza a série 2016-2025).
        mun_col = _col(df, ["id_mn_resi", "co_municipio_residencia", "id_municip", "co_municipio_notificacao"])
        if mun_col is not None:
            df = _filtrar_municipio(df, mun_col)

        bairro_col = _col(df, ["nm_bairro", "no_bairro_residencia", "no_bai", "nm_bai"])
        geocod_col = _col(df, ["id_bairro", "co_bairro_residencia", "co_bai"])
        semana_col = _col(df, ["sem_not", "sem_pri", "ds_semana_notificacao", "ds_semana",
                               "semana_notificacao", "semana"])

        # Filtra notificações descartadas (classificação final = 5) antes de agregar casos.
        class_col = _col(df, ["classi_fin", "tp_classificacao_final"])
        if class_col is not None:
            df = _filtrar_descartados(df, class_col)

        n_recife = len(df)
        if bairro_col is not None:
            bairro_norm_series = df[bairro_col].apply(_norm)
            missing_bairro = int(bairro_norm_series.isna().sum())
        else:
            bairro_norm_series = pd.Series([None] * n_recife, index=df.index)
            missing_bairro = n_recife
        if geocod_col is not None:
            geocod_norm = df[geocod_col].apply(_norm)
            missing_geocod = int(geocod_norm.isna().sum())
        else:
            missing_geocod = n_recife

        if semana_col is not None and bairro_col is not None:
            work = pd.DataFrame({
                "bairro_norm": bairro_norm_series.values,
                "semana": pd.to_numeric(df[semana_col], errors="coerce"),
            }, index=df.index)
            work = work.dropna(subset=["semana"])
            work["semana"] = work["semana"].astype(int)
            work["bairro_canon"] = work["bairro_norm"].map(lambda x: canon.get(x, x) if x else None)

            agg = (work.dropna(subset=["bairro_canon"])
                   .groupby(["bairro_canon", "semana"]).size()
                   .reset_index(name="casos"))
            agg = agg.rename(columns={"bairro_canon": "bairro"})

            distinct_raw = set(work["bairro_norm"].dropna().unique())
            unmapped = sorted(b for b in distinct_raw if b not in canon)
            # Registros cujo bairro existe, mas não está no mapeamento canônico (contam no pct_sem_bairro).
            n_nao_mapeado = int(bairro_norm_series.isin(set(unmapped)).sum())
        else:
            agg = pd.DataFrame(columns=["bairro", "semana", "casos"])
            unmapped = []
            n_nao_mapeado = 0

        for _, r in agg.iterrows():
            rows_out.append({
                "bairro": r["bairro"],
                "semana": int(r["semana"]),
                "casos": int(r["casos"]),
                "ano": year,
            })

        total_year = int(agg["casos"].sum()) if len(agg) else 0
        report["anos"][str(year)] = {
            "registros_total_ckan": int(n_total),
            "registros_recife": int(n_recife),
            "registros_com_semana": int(len(work)) if (semana_col is not None and bairro_col is not None) else 0,
            "casos_agregados": total_year,
            "bairros_distintos": int(agg["bairro"].nunique()) if len(agg) else 0,
            "semanas_distintas": int(agg["semana"].nunique()) if len(agg) else 0,
            "pct_sem_bairro": round(100 * (missing_bairro + n_nao_mapeado) / n_recife, 2) if n_recife else 0.0,
            "pct_sem_geocod": round(100 * missing_geocod / n_recife, 2) if n_recife else 0.0,
            "bairros_nao_mapeados": unmapped,
            "col_bairro": bairro_col,
            "col_geocod": geocod_col,
            "col_semana": semana_col,
        }
        epidemic.append((year, total_year))
        print(f"{year}: recife={n_recife} casos={total_year} "
              f"bairros={agg['bairro'].nunique() if len(agg) else 0} "
              f"pct_sem_bairro={report['anos'][str(year)]['pct_sem_bairro']}% "
              f"pct_sem_geocod={report['anos'][str(year)]['pct_sem_geocod']}% "
              f"nao_mapeados={len(unmapped)}")

    # Anos epidêmicos: anos com total anual >= 3º quartil (top 25%) da série.
    totals = [t for _, t in epidemic]
    q3 = float(np.percentile(totals, 75))
    epidemic_years = sorted(y for y, t in epidemic if t >= q3)

    report["epidemic_years"] = epidemic_years
    report["metodo_anos_epidemicos"] = "total anual >= 3º quartil (p75) da série 2016-2025"
    report["threshold_casos"] = round(q3, 1)
    report["quartis"] = {
        "p25": round(float(np.percentile(totals, 25)), 1),
        "p50": round(float(np.percentile(totals, 50)), 1),
        "p75": round(q3, 1),
    }
    report["media_casos_anual"] = round(statistics.mean(totals), 1)
    report["desvio_padrao"] = round(statistics.pstdev(totals), 1)
    report["totais_por_ano"] = {str(y): t for y, t in epidemic}

    out_df = _reagregar(pd.DataFrame(rows_out, columns=["bairro", "semana", "casos", "ano"]))

    out_path = config.DATA_DIR / "sinan_bairro_se_2016_2025.csv"
    out_df.to_csv(out_path, index=False)
    report_path = config.DATA_DIR / "sinan_bairro_se_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== ANOS EPIDÊMICOS (>= p75):", epidemic_years)
    print("threshold (p75):", round(q3, 1), "| média:", round(statistics.mean(totals), 1))
    print("salvo:", out_path, "|", len(out_df), "linhas")
    print("salvo:", report_path)


if __name__ == "__main__":
    main()
