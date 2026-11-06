# SP-3 — Validação temporal (rolling-origin) e vazamento

**Ticket:** PUL-10 · Squad Inteligência · Sprint 0 (Context: Análise de Risco)
**Autor:** Pedro Bedor · **Timebox:** 1 dia · **Data:** 2026-11-05
**Demo executável:** `backend/notebooks/sp3_rolling_origin.py` (rodar `cd backend && ./venv/bin/python notebooks/sp3_rolling_origin.py`; painel real 2024–25, seed 42, git `d535414`; ~46 modelos XGBoost com `config.FORECAST_XGB_PARAMS`)
**Alimenta:** US26 (gate de promoção), US23 (baselines), US14 (teste canário de feature), US22 (canal endêmico)

> **Conclusão em 3 linhas:** o corte único atual (`202520`) fica numa região favorável — com rolling-origin de 10 origens, o XGBoost **perde da persistência em média no h=3** (skill 1,017) e em 40% dos folds no h=2/h=3. Uma divisão aleatório infla a vantagem aparente do modelo: o MAE sai **12–22% mais otimista** que com divisão temporal. Há 4 riscos de vazamento ativos/relevantes no pipeline hoje (Tabela 2), com mitigação definida (as-of L=2 semanas + teste canário).

---

## 1. Esquema de rolling-origin (dois níveis)

**Painel:** bairro × SE CDC (regra por horizonte `h ∈ 1..4`, alvo `y_h = casos em t+h`).
**Regra de purge (todas as dobras):** linha de treino só entra se `widx + h ≤ origem`; linhas de teste têm `widx > origem`. Isso garante que nenhum alvo de treino toca o período avaliado (salvaguarda que o backtest atual já aplica — manter).

### Nível 1 — dobras por temporada (reporte e promoção; US26)

Dois caminhos foram implementados e comparados com dados reais:

| Caminho | Fronteira | Fold(s) no painel atual | Resultado h=1 (MAE XGB / persist) |
|---|---|---|---|
| **A — ano civil CDC** | virada W52→W01 | treino ≤ `202452`, teste 2025 | **1,166 / 1,287** (skill 0,91; P@10 0,61 vs 0,55) |
| **B — ano epidêmico** | vale derivado do perfil: `W2`* | treino ≤ `202502`, teste resto | **1,168 / 1,297** (skill 0,90; P@10 0,64 vs 0,57) |

\* **Achado honesto:** com só 2 temporadas (2024 endêmica + 2025 epidêmica) o perfil semanal não mostra vale de transmissão — a fronteira derivada (W2) degenera para perto da virada civil e **A ≈ B nas métricas**. A escolha da fronteira fica **adiada para quando o SINAN 2016+ (US04) chegar**; o método (mínimo da média móvel circular do perfil por week-of-year) está no script e é recomputável. Com ≥5 temporadas, o caminho B deve ser reavaliado — é o que o plano §6.3 pede ("rolling-origin por temporada").

### Nível 2 — passo fixo, expanding window (diagnóstico; US26 + depuração)

10 origens a cada **6 semanas**, treino mínimo **39 semanas** (≥1 temporada), teste = 6 semanas seguintes. Matriz `skill = MAE_xgb / MAE_persist` por origem (negrito = pior que persistência):

| origem | h=1 | h=2 | h=3 | h=4 |
|---|---|---|---|---|
| 202440 | 0,97 | **1,07** | **1,15** | **1,25** |
| 202446 | 0,99 | **1,41** | **1,64** | **1,49** |
| 202452 | 0,85 | 0,88 | 0,91 | 0,96 |
| 202506 | 0,95 | 0,92 | 0,92 | 0,86 |
| 202512 | 0,91 | 0,86 | 0,86 | 0,80 |
| 202518 | 0,82 | **1,10** | **1,01** | 0,80 |
| 202524 | **1,03** | **1,02** | **1,09** | **1,18** |
| 202530 | 0,93 | 0,90 | 0,88 | 0,88 |
| 202536 | 0,83 | 0,79 | 0,80 | 0,77 |
| 202542 | 0,98 | 0,89 | 0,92 | 0,84 |

Agregado: skill médio h=1 0,925 (**90%** dos folds acima da persistência), h=2 0,982 (60%), h=3 **1,017** (60%), h=4 0,983 (70%). Acima do sazonal-ingênuo em 80% dos folds em todos os h. P@10 do XGBoost supera a persistência em todas as origens/h.

**Leitura:** os folds que perdem são (a) os mais antigos (202440/202446: treino curto, virada para a epidemia de 2025) e (b) 202524 (pós-pico, declínio rápido — fase difícil para qualquer modelo). O cutoff atual `202520` é justamente um ponto favorável: **um único hold-out não representa o histórico** — é a evidência central desta spike (risco R3).

### Regra as-of (atraso de notificação) — do cache SINAN real

Atraso `DT_NOTIFIC − DT_SIN_PRI`: **p50 = 5 d, p75 = 8 d, p90 = 17 d** (n=18.267). Curva de revisão (fração do total FINAL de uma SE já notificada L semanas após o fechamento dela):

| L (semanas) | 0 | 1 | 2 | 3 | 4 | 6 |
|---|---|---|---|---|---|---|
| cobertura média | 0,35 | 0,80 | **0,90** | 0,94 | 0,96 | 0,99 |
| p10 das semanas | 0,24 | 0,69 | 0,82 | 0,88 | 0,91 | 0,96 |

**Regra proposta:** o modelo de produção deve ser avaliado/servido como se previsse **a partir da última SE com ≥ L=2 semanas de consolidação** — é exatamente o que a seleção de cobertura da API já faz na prática (`complete_case_weeks` + `DadosIndisponiveis`), mas a validação ainda não emulate isso: no treino, os features da semana de origem usam SINAN **assentado**, indisponível em tempo real (risco R2). Para o gate da US26, implementar "painel as-of" (reconstruir `casos` filtrando por `DT_NOTIFIC ≤ fim(t) − L` antes de calcular lags) e reportar a métrica sob as-of como a métrica oficial.

## 2. Riscos de vazamento no pipeline atual

Severidade: 🔴 alto / 🟠 médio / 🟢 baixo. "Evidência" = arquivo no `backend/`.

| # | Risco | Evidência | Efeito | Sev. | Mitigação |
|---|---|---|---|---|---|
| R1 | **`hist`/`vuln` estáticos com conhecimento posterior**: scores atribuídos à mão por "surtos documentados 2015–**2024**" e ajuste nominal por bairro | `scripts/build_bairros_lookup.py:117–130` | em folds com origem em 2024 (nível 2: 202440/202446), `hist` codifica informação posterior à origem → infla métricas dos primeiros folds | 🔴 | registrar a janela de conhecimento por feature; no limite, regravar `hist` só com fonte pré-origem ou removê-la do treino validado (US19) |
| R2 | **Assentamento do SINAN vs. disponibilidade em tempo real** ("ausência vira 0 dentro da cobertura publicada" usa a publicação final; treino tem casos consolidados que a produção não terá na mesma SE) | `app/services/forecast_features.py:76–79`, `data_sync.complete_case_weeks` | features `casos`/lags em t mais "completos" no treino que em serving → queda real de performance não medida (apenas 35% dos casos de uma SE estão notificados no fechamento dela; ~65% chegam depois — Tabela 1) | 🔴 | regra as-of L=2 (seção 1); painel as-of no gate da US26 |
| R3 | **Overfitting de seleção num cutoff único**: iterações de params/gate olham sempre a janela `>202520` | `config.py` `FORECAST_BACKTEST_CUTOFF`; `scripts/export_model.py:gate` | métricas oficiais = melhor fold possível (evidência: matriz nível 2) | 🟠→🔴 com iteração contínua | rolling-origin nível 1/2 como protocolo de gate (US26) |
| R4 | **Features contemporâneos de t exigem semana t fechada** (`casos`, `chuva_mm` em t; `vizinhos_ds` = média dos **outros bairros** do mesmo DS na semana t) | `forecast_features.py:114–117`; `forecast_serving.get_featured_panel:39–42` | em produção a semana mais recente é descartável/incompleta; o filtro `eligible` remove semanas inteiras → distribuição de serving ≠ treino (agrava R2) | 🟠 | deixar a origem do fold na "última SE elegível as-of", não na última SE do painel |
| R5 | **Métrica não descreve o modelo servido**: final retreina com todo o histórico, incluindo o teste | `scripts/train_forecast.py:130–133` | practice aceita, mas precisa ser documentada no model card | 🟢 | texto do model card (US35); esperar métrica do último fold como "expectativa honesta" |
| R6 | **Salvaguardas que já existem** (registrar para não regredir): lags/rollings com `shift(1)`, alvo só via `shift(-h)`, purge `widx+h ≤ cutoff`, clima semanal só de semanas fechadas | `forecast_features.py:86–106`; `train_forecast.py:111–112` | — | 🟢 | teste canário da US14: perturbar dados de semanas futuras não pode alterar features ≤ t |
| R7 | **SE por `DT_SIN_PRI` (decisão da S0 pendente)** reatribui casos retroativamente a semanas passadas → painel vira série revisada (backfill) | glossário §5.3; `normalize_sinan` hoje usa `DT_NOTIFIC` | se adotada sem as-of, treino usa "passado corrigido" que a produção nunca viu; com as-of, é a base correta do canal endêmico | 🔴 (se adotada) | decisão S0 explícita + curva de revisão desta spike como insumo |
| R8 | **Canal endêmico calculado no período inteiro** ("mediana/quartis de 5–7 anos não epidêmicos" + identificação de anos epidêmicos olhando 2016–2025) | plano §6.3; US22; US04 critério "anos epidêmicos identificados" | rótulo "alto risco" e baseline do canal vazariam o futuro para folds antigos → recall de alto risco inflado | 🔴 (futuro) | canal **walk-forward**: só temporadas anteriores à origem do fold |
| R9 | **Saídas de análise global virarem features**: clusters de perfil (US21) e hotspots LISA (US20) calculados com o período todo | plano §6.3; E5 | mesmo padrão de R1 (estático informed-consent) | 🟠 (futuro) | LISA por temporada usando só dados ≤ origem; rótulo de cluster tratado como estático pré-2016 se derivado só de censitário |
| R10 | **Ovitrampas (US12)**: ciclo de medição + processamento de laboratório → IPO/IDO de t disponível só depois de t | plano §7; pedido SMS | mesma família de R2, novo lag por fonte | 🟠 (futuro) | registrar lag por fonte no data card; regra as-of genérica `≤ t − L(fonte)` |

## 3. Por que métrica infla com CV aleatório (demonstração)

Mesmo modelo/params, mesmo tamanho de teste (~30% das linhas), só muda a **forma de dividir**:

| h | MAE "aleatório" | MAE temporal | inflação | P@10 aleatório | P@10 temporal |
|---|---|---|---|---|---|
| 1 | 1,147 | 1,304 | **−12,0%** | 0,680 | 0,633 |
| 2 | 1,166 | 1,362 | **−14,4%** | 0,692 | 0,623 |
| 3 | 1,207 | 1,422 | **−15,1%** | 0,693 | 0,600 |
| 4 | 1,175 | 1,498 | **−21,6%** | 0,688 | 0,591 |

Com CV aleatório, o treino contém a vizinhança temporal imediata de cada linha de teste (lags do próprio bairro, `vizinhos_ds` da mesma semana) — informação que a previsão real não tem. O efeito cresce com `h`. **Toda e qualquer métrica deste projeto deve vir de divisão temporal com purge.**

## 4. Proposta de gate para a US26 (a decidir com orientador)

Métricas oficiais = nível 1 (por temporada, ≥5 folds quando 2016+ chegar) com painel as-of (R2); nível 2 para diagnóstico em CI. Critério de promoção sugerido por horizonte h:

1. `MAE_xgb` menor que **ambos** os baselines (persistência e canal endêmico — US23) na **mediana** dos folds;
2. `MAE_xgb` melhor que persistência em **≥ 80% dos folds** (hoje, com os dados disponíveis: h=1 ✅ 90%; h=4 70% ❌ — o limiar exato é decisão do squad);
3. `P@K_xgb` ≥ `P@K_persistência` em todos os folds;
4. (futuro) recall de alto risco ≥ baseline do canal endêmico, conforme US26.

## 5. Limitações da demo

- 2 temporadas: nível 1 com 1 fold por caminho; a comparação A×B é ilustrativa, não conclusiva.
- Baseline sazonal-ingênuo colapsa na virada 2024→2025 (2025 epidêmico sem análogo em 2024 — MAE 4,3 no fold 202506); esperado, reforça a necessidade de 2016+.
- Params do modelo não foram ajustados para a demo (mesmos de produção, sem early stopping); o objetivo é o **esquema**, não o melhor número.
- O cache SINAN tem registros com `DT_SIN_PRI` de erro de digitação que chegam a décadas de atraso; a demo restringe a curva às semanas de sintomas do período do painel (n=18.267, max 379 d), mas a limpeza da US04 deve tratar a origem.
- O painel usado é o da `main` (SINAN 2024–25 municipal + APAC média da cidade); quando o painel da US14 versionar (chuva por DS, população), o script roda sobre ele sem mudanças estruturais.

## 6. Próximos passos / ligações

- [ ] US26 adota o esquema (nível 1 como oficial, nível 2 em CI) e o painel as-of — usar esta doc como spec.
- [ ] US14 implementa o teste canário (R6) e o schema do painel com data de "assentamento" por fonte.
- [ ] US23 roda persistência/sazonal/canal no mesmo harness (`avaliar_step` já aceita baselines).
- [ ] US22 documenta o canal walk-forward (R8) antes de usá-lo como rótulo.
- [ ] S0 (US01): registrar decisão SE por `DT_NOTIFIC` vs `DT_SIN_PRI` com esta curva de revisão em mãos (R7).
- [ ] Apresentar 15 min na sessão com o orientador (padrão das spikes §6.4).
