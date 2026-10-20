"""Histórico Pluviométrico vinculado em dadosApac/, sem API presumida."""
from datetime import date
from html.parser import HTMLParser
import math

import pandas as pd

from app import config


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            self.tables.append(self.rows)
            self.rows = None


def parse_diario(html: str, start: date, end: date) -> pd.DataFrame:
    """Tabela estação/mês/dias -> leituras únicas. '-' permanece ausente."""
    parser = _Tables()
    parser.feed(html)
    required = {"Código GMMC", "Município", "Estação", "Ano/Mês", "01", "31"}
    tables = [t for t in parser.tables if t and required.issubset(t[0])]
    if len(tables) != 1:
        raise ValueError("APAC: tabela diária ausente ou formato alterado")
    headers, *rows = tables[0]
    readings = []
    for cells in rows:
        if len(cells) != len(headers):
            raise ValueError("APAC: linha com número inesperado de colunas")
        row = dict(zip(headers, cells))
        if row["Município"].strip().casefold() != "recife":
            continue
        year, month = map(int, row["Ano/Mês"].split("/"))
        station = row["Código GMMC"].strip()
        if not station:
            raise ValueError("APAC: estação sem código GMMC")
        for day in range(1, 32):
            try:
                dt = date(year, month, day)
            except ValueError:
                continue
            if not start <= dt <= end:
                continue
            raw = row[f"{day:02d}"].strip()
            if raw in ("", "-", "—"):
                continue
            value = float(raw.replace(".", "").replace(",", ".")) if "," in raw else float(raw)
            if not math.isfinite(value) or value < 0:
                raise ValueError("APAC: precipitação inválida")
            readings.append({"data": dt.isoformat(), "estacao": station,
                             "nome": row["Estação"], "chuva_mm": value})
    if not readings:
        raise ValueError("APAC: nenhuma leitura válida de Recife no período")
    df = pd.DataFrame(readings)
    if (df.groupby(["data", "estacao"])["chuva_mm"].nunique() > 1).any():
        raise ValueError("APAC: leituras conflitantes para estação/data")
    return df.drop_duplicates(["data", "estacao"]).sort_values(["data", "estacao"])


def download_diario(session, start: date, end: date):
    response = session.post(config.APAC_HISTORICO_DIARIO_URL, data={
        "mesorregiao": "Metropolitana de Recife", "microrregiao": "Todas",
        "municipio": "Recife", "bacia": "Todas", "tipoBoletim": "Diário",
        "dataInicial": start.isoformat(), "dataFinal": end.isoformat(),
    }, timeout=(10, 90))
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_diario(response.text, start, end), response.text


def get_clima_semana(year: int) -> pd.DataFrame:
    """Cache histórico versionado; indisponibilidade nunca vira chuva sintética."""
    path = config.CACHE_DIR / f"apac_clima_semana_{year}.csv"
    columns = ["semana", "chuva_mm", "temp_media", "temp_max", "dias"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path)
    df.loc[df["dias"] != 7, ["chuva_mm", "temp_media", "temp_max"]] = float("nan")
    return df[columns]
