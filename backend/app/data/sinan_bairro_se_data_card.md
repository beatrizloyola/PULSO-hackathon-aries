# Data card — Histórico SINAN de dengue por bairro × semana (2016–2025)

## Resumo

| Campo | Valor |
|---|---|
| Arquivo de dados | `sinan_bairro_se_2016_2025.csv` |
| Relatório de geração | `sinan_bairro_se_report.json` |
| Fonte | CKAN Dados Abertos do Recife — dataset "Casos de Dengue, Zika e Chikungunya" (`DATASET_DENGUE_ID` em `app/config.py`) |
| Cobertura | Recife, 2016–2025 |
| Grão | bairro × semana epidemiológica (SE) |
| Unidade | casos notificados de dengue (excluindo descartados) |
| Script | `backend/scripts/build_sinan_historico.py` |

## Colunas

| Coluna | Descrição |
|---|---|
| `bairro` | Nome canônico do bairro (via `bairros_lookup.json`). Bairros fora do lookup mantêm a grafia normalizada da fonte. |
| `semana` | Semana epidemiológica no formato `YYYYWW` (ex.: `202401`). |
| `casos` | Contagem de notificações não descartadas naquele bairro/semana. |
| `ano` | Derivado da semana (`semana // 100`). |

O grão é único: não há mais de uma linha por `(bairro, semana)`.

## Pipeline

1. **Filtro de município:** mantém apenas registros cujo **município de residência** é Recife (`261160`), em todos os anos. Anos anteriores a 2021 não tinham esse filtro e 2021–2025 usavam município de notificação; usar residência evita a quebra da série em 2021.
2. **Filtro de classificação:** remove notificações com classificação final **5 (descartado)** antes de agregar. Em 2024 isso corresponde a ~75% dos registros; sem o filtro, os anos epidêmicos ficam distorcidos.
3. **Normalização de bairro:** caixa alta, remoção de acentos e de sentinelas (`IGNORADO`, `NÃO INFORMADO`, `OUTROS`, etc.), com mapeamento para o nome canônico em `bairros_lookup.json`.
4. **Agregação:** conta casos por `(bairro, semana)` e, no fim, reagrega novamente por `(bairro, semana)` para eliminar duplicatas.
5. **Ano:** derivado da semana (`semana // 100`).

## Limitações conhecidas

- **Bairros não mapeados** (`CENTRO`, `ZONA RURAL`, grafias quebradas como `JIQU]`, `VASCO`/`VASC`, etc.) permanecem na série com a grafia normalizada e aparecem em `bairros_nao_mapeados` no relatório. O `pct_sem_bairro` inclui esses registros.
- **Chave da tabela:** hoje é o **nome** do bairro, não o código. O alinhamento com o código do bairro (e o tratamento dos não mapeados) fica para um próximo PR, conforme alinhado com a Bia.
- **Semana de referência:** derivada da semana de notificação (`ds_semana_notificacao` / `SEM_NOT`), não da semana de início de sintomas.
- **Dados brutos:** os CSVs anuais baixados do CKAN ficam em `app/data/cache/` e **não são versionados** (ver `.gitignore`). Eles são regeneráveis pelo script.

## Relatório (`sinan_bairro_se_report.json`)

Traz, por ano: total de registros no CKAN, registros de Recife após filtros, casos agregados, bairros/semanas distintas, `pct_sem_bairro`, `pct_sem_geocod`, lista de bairros não mapeados e as colunas usadas de cada arquivo.

Anos epidêmicos são definidos como anos com total anual ≥ **3º quartil (p75)** da série 2016–2025.

## Regeneração

```bash
cd backend
python scripts/build_sinan_historico.py
```

O script baixa os CSVs anuais do CKAN quando não há cache local e escreve os dois arquivos acima em `app/data/`.
