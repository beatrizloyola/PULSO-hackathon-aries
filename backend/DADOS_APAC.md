# Coleta e atualização dos dados

## Fonte oficial e método

O ponto de entrada é o [portal Dados APAC](http://dados.apac.pe.gov.br:41120/dadosApac/).
Seu menu **Boletins → Histórico Pluviométrico** aponta para
`/boletins/historico-pluviometrico/`. A opção **Diário** envia um POST para
`diario.php` com `municipio=Recife`, `mesorregiao=Metropolitana de Recife`,
`microrregiao=Todas`, `bacia=Todas`, `tipoBoletim=Diário`, `dataInicial` e `dataFinal`.
O cliente usa exatamente esse formulário, com uma consulta por ano até ontem,
sem inventar uma API JSON. O link oficial usa HTTP e a porta 41120.

A resposta contém uma linha por estação/mês: Código GMMC, município, estação,
Ano/Mês e colunas 01–31. São preservados os números decimais brasileiros e
as leituras de zero. `-` é uma leitura ausente. Formato inesperado, precipitação
inválida ou valores conflitantes para estação/data interrompem a publicação.
As estações são as publicadas pela APAC, incluindo redes parceiras, como CEMADEN.

A série de Recife é a **média das estações com leitura válida em cada dia**,
seguida da soma dos sete dias da semana epidemiológica CDC. Isso representa o
município, não a precipitação medida em cada bairro. O número de estações é
registrado; mudanças da rede podem alterar essa média. Não há interpolação
espacial ou validação instrumental adicional. Uma semana só é elegível quando
há chuva e temperatura nos sete dias, além do histórico exigido pelo modelo.

A temperatura histórica continua no Open-Meteo, com atribuição separada.
`temp_max` mantém a definição do modelo: média das máximas diárias na semana.
As notificações vêm dos CSVs anuais de dengue descobertos no catálogo CKAN do
Recife. As semanas são calculadas a partir de `DT_NOTIFIC`, com a mesma regra CDC.
A cobertura é limitada à última data de notificação publicada e às semanas já
encerradas; isso não comprova completude de notificação nem corrige subnotificação.

## Operação

Com o ambiente Python ativado, execute dentro de `backend/`:

```bash
python -m scripts.atualizar_dados --force
python -m app.main
```

O servidor inicia um trabalhador em segundo plano. `DATA_REFRESH_SECONDS`
controla a validade da coleta (padrão 86400 segundos). Ele verifica a necessidade
de atualização a cada hora e tenta novamente em caso de falha. Um lock de arquivo
impede coletas simultâneas entre processos Linux. O caminho da API não espera a
rede: continua atendendo com o último snapshot válido ou com o histórico APAC
versionado. O frontend consulta o ranking novamente a cada cinco minutos.

Variáveis de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `AUTO_SYNC` | `true` | `false` desativa a coleta em segundo plano |
| `DATA_REFRESH_SECONDS` | `86400` | Validade da coleta, mínimo de 60 segundos |
| `DATA_START_YEAR` | `2024` | Primeiro ano consultado |
| `APAC_HISTORICO_DIARIO_URL` | URL oficial `diario.php` | Sobrescrever endpoint se o portal mudar |
| `CKAN_BASE_URL` | `https://dados.recife.pe.gov.br` | Catálogo epidemiológico |
| `OPENMETEO_ARCHIVE_URL` | API archive Open-Meteo | Temperatura histórica |

Também é possível agendar `python -m scripts.atualizar_dados` externamente e
usar `AUTO_SYNC=false` no servidor. Não existe endpoint público que force downloads.

## Cache, falhas e rastreabilidade

Cada coleta cria um diretório em `app/data/cache/atualizacao/` com tabelas APAC
originais, leituras normalizadas, resposta de temperatura, agregados semanais e
metadados. Não persiste novos registros individuais do SINAN: somente agregados
por bairro/semana, URLs e hashes SHA-256 dos arquivos de origem. Os downloads
runtime ficam fora do Git. Os snapshots são mantidos para auditoria; monitore
o uso de disco e retenha os necessários conforme a operação.

`current.json` é substituído atomicamente somente depois de validar todas as
fontes e a existência de cinco semanas consecutivas completas. Cobertura que
retrocede não substitui o snapshot válido. `attempt.json` registra sucesso ou
falha da tentativa. Falha não converte dados ausentes em zero nem troca a chuva
por outra fonte. A API detecta um novo snapshot sem precisar reiniciar.

A resposta de `/prioridade` inclui `dados.coletado_em`, `dados.chuva_ate`,
`dados.casos_ate`, `dados.desatualizados` e `dados.avisos`, além das semanas
realmente elegíveis e fontes. Há aviso quando a coleta falha/atrasa, quando
somente o histórico local está disponível, ou quando a última semana comum está
mais de 21 dias atrás. Essa indicação informa disponibilidade, não validação
científica da previsão.

Na consulta real de **24/09/2026**, a APAC retornou chuva até **23/09/2026**;
o catálogo epidemiológico consultado publicou dengue somente até **31/12/2025**.
Por isso a última referência utilizável foi **2025-W52**. O sistema não apresenta
uma previsão de 2026 só porque o clima está atualizado.

## Modelo e validação

A atualização do cache não retreina automaticamente o modelo. Para recalibrar e
avaliar os quatro horizontes com o snapshot atual:

```bash
python -m scripts.train_forecast
```

O treinamento usa os anos em `FORECAST_ANOS` e separação temporal: alvos do treino
até o corte; referências de teste posteriores ao corte. Avalia MAE e precisão@10
contra persistência e grava métricas/proveniência em `forecast_meta.json`.
Confira essas métricas antes de publicar novos modelos. As telas leem as métricas
desse arquivo pela API. Após substituir modelos num servidor em execução,
reinicie o processo para recarregá-los.

## Testes

```bash
AUTO_SYNC=false python -m pytest tests -q
```

A fixture de HTML contém a tabela oficial de Recife consultada para 20–23/09/2026.
Os testes não usam rede e cobrem parsing, ausência versus zero, média espacial,
semanas CDC, semanas incompletas, alinhamento com casos, falhas de coleta,
publicação de snapshot, invalidação do painel e resposta da API/mapa.
