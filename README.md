# PULSO

Inteligência para Priorização da Vigilância em Saúde. Acesse [aqui](https://sistemapulso.up.railway.app/).

PULSO é uma ferramenta de apoio à decisão para a Vigilância em Saúde de Recife.
Ela transforma sinais epidemiológicos, climáticos e territoriais em uma fila
dinâmica de prioridades operacionais, com corte pela capacidade de equipes
disponíveis no momento.

**PULSO não é um dashboard de monitoramento climático.** A pergunta que o
produto responde é: *"Tenho equipes limitadas e vários territórios pedindo
atenção — onde ajo primeiro?"* O clima é um sinal de entrada entre vários,
não a identidade do produto. O sistema recomenda; o profissional decide.

## Stack

- **Frontend:** React 19 + Vite, CSS puro. SPA com navegação entre 6 telas controlada por estado.
- **Backend:** Python (Flask) com XGBoost, pandas, scikit-learn. consome dados reais do CKAN (dengue), APAC (chuva) e GIS (bairros/ZEIS).
- **ML:** Quatro modelos XGBoost de contagem, com 18 variáveis e horizontes de 1 a 4 semanas. Métricas em `backend/app/models/forecast_meta.json`.

## Como rodar localmente

### 1. Backend (Python)

```bash
cd backend
# Criar e ativar ambiente virtual (opcional mas recomendado)
python3.12 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Instalar dependências
pip install -r requirements.txt

# Rodar o servidor Flask
python -m app.main
```

O backend sobe em **http://localhost:8000** e coleta dados em segundo plano. Veja [coleta, cobertura e testes](backend/DADOS_APAC.md).

### 2. Frontend (React + Vite)

```bash
# Na raiz do projeto
npm install
npm run dev      # ambiente de desenvolvimento, http://localhost:5173
npm run build    # build de produção em dist/
npm run preview  # serve o build de produção localmente
npm run lint     # oxlint
```

### Ambiente de desenvolvimento completo

Em terminais separados:

```bash
# Terminal 1 — Backend
cd backend
source venv/bin/activate
python -m app.main

# Terminal 2 — Frontend (raiz do projeto)
npm run dev
```

Acesse o frontend em **http://localhost:5173**. Ele se comunica automaticamente com o backend em **http://localhost:8000**.

## Estrutura do projeto

```
backend/
  app/
    main.py              # servidor Flask (endpoints /prioridade, /mapa, /health)
    config.py            # fontes, atualização e parâmetros dos modelos
    data/
      bairros_lookup.json        # 94 bairros com scores de vulnerabilidade/histórico
      bairros_esig.geojson       # polígonos reais dos bairros (fonte: ESIG)
      training_data.csv          # dataset de treinamento do modelo
    services/
      model.py             # XGBoost: treinamento, predição, explicabilidade
      data_sync.py         # coleta periódica APAC/SINAN/temperatura
      apac_client.py       # formulário oficial e leitura das tabelas APAC
      forecast_features.py # painel semanal alinhado e variáveis do modelo
      forecast_serving.py  # seleção de semanas com dados suficientes
    models/
      forecast_h1.json     # modelos forecast_h1 a forecast_h4
      forecast_meta.json   # fontes, período de treino e validação temporal
  requirements.txt

src/
  data/
    priorizacao.js       # PESOS_PRIORIZACAO para exibição frontend
  context/
    PulsoContext.jsx     # estado global: capacidade, seleção, decisões, fila ordenada
  components/
    Sidebar.jsx, Header.jsx, BadgeClassificacao.jsx
    ModalFontesDados.jsx   # modal com fontes de dados do ML
    ModalAlgoritmo.jsx     # modal explicando o algoritmo XGBoost
    MapaRecife.jsx         # mapa interativo com polígonos de bairros
  screens/
    TelaVisaoGeral.jsx       # Tela 1 — Central de Decisão
    TelaPrioridades.jsx      # Tela 2 — Fila Dinâmica de Prioridades
    TelaExplicacao.jsx       # Tela 3 — Explicação da Prioridade
    TelaRecomendacao.jsx     # Tela 4 — Recomendação Operacional
    TelaPlanejamento.jsx     # Tela 5 — Planejamento de Capacidade
    TelaAcoesResultados.jsx  # Tela 6 — Ações e Resultados
    Telas.css                 # estilos específicos de cada tela
  index.css   # tokens de design globais
  App.css     # layout (sidebar, header, shell)
```

## Modelo de priorização (ML)

O PULSO prevê casos por bairro com XGBoost (`count:poisson`). Os 18 sinais
incluem casos atuais e defasados, tendências, chuva APAC, temperatura de apoio,
sazonalidade, atributos territoriais e casos dos demais bairros do mesmo DS.
O índice de prioridade é `100 × casos_previstos / (casos_previstos + 5)`.

A chuva vem do [portal Dados APAC](http://dados.apac.pe.gov.br:41120/dadosApac/),
via Histórico Pluviométrico. O sistema calcula a média diária das estações de
Recife e soma os sete dias da semana epidemiológica CDC. É uma aproximação
municipal compartilhada pelos bairros, não uma medição de cada bairro.

A API oferece somente semanas com clima completo, cobertura de notificações e
histórico suficiente. A seleção inicial usa a última dessas semanas. Se o
SINAN estiver atrasado, chuva recente não adianta artificialmente a previsão.
A interface informa fonte, data da coleta e limitações de cobertura.

A validação temporal compara MAE e precisão@10 com persistência. As métricas
exibidas vêm do modelo salvo, sem valores fixos no frontend. Atualizar a coleta
não retreina automaticamente os modelos; o procedimento está em
[backend/DADOS_APAC.md](backend/DADOS_APAC.md).

## Estado global (`PulsoContext`)

- `territoriosOrdenados` — 94 bairros ordenados por score do modelo (desc).
- `capacidadeEquipes` — número de equipes disponíveis (default: 6, editável na
  Tela 5, máx: 10).
- `cobertura` — derivado via `useMemo`: quem está coberto/em acompanhamento
  e o percentual de cobertura potencial, recalculado sempre que a capacidade
  muda.
- `territorioSelecionado` — controla qual território as Telas 3 e 4 exibem.
- `decisoes` — decisões registradas, exibidas na Tela 6.

## As 6 telas

1. **Visão Geral** — métricas operacionais, card de recomendação, grade territorial
   de risco (94 bairros), Top 8, mapa interativo com polígonos reais dos bairros.
2. **Prioridades** — Top 3 em cards + tabela de fila de acompanhamento, stepper de
   capacidade.
3. **Explicação** — componentes epidemiológicos, climáticos e territoriais usados como contexto da priorização.
4. **Recomendação** — ações checklists por classificação, recursos dinâmicos,
   setores envolvidos, alerta de sobrecarga operacional.
5. **Planejamento** — stepper de capacidade (1–10); cards de cobertos vs.
   acompanhamento (top 15 visíveis), comparativo de cenários.
6. **Ações e Resultados** — decisões registradas + KPIs de processo.

## Fontes de dados externas

- **CKAN Recife:** https://dados.recife.pe.gov.br — notificações de dengue (SINAN)
- **APAC:** http://dados.apac.pe.gov.br:41120/dadosApac/ — chuva diária do Recife (temperatura de apoio: Open-Meteo archive)
- **ESIG:** https://esigportal2.recife.pe.gov.br — polígonos dos 94 bairros e ZEIS
