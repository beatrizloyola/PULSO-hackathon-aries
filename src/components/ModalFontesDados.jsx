import { useState, useEffect } from "react";

const FONTES = [
  {
    nome: "CKAN - Portal de Dados Abertos do Recife",
    url: "https://dados.recife.pe.gov.br",
    tipo: "Dados epidemiológicos",
    descricao:
      "Notificações de dengue (SINAN) agregadas por bairro e semana epidemiológica a partir de NM_BAIRRO, DT_NOTIFIC e ID_MUNICIP.",
    atualizacao: "Semanal",
    registros: "Cobertura conforme os arquivos publicados no catálogo",
    variaveis: ["casos_semana_atual", "casos_semana_anterior", "tendencia_epidemiologica"],
  },
  {
    nome: "APAC - Agência Pernambucana de Águas e Clima",
    url: "http://dados.apac.pe.gov.br:41120/dadosApac/",
    tipo: "Dados climáticos",
    descricao:
      "Histórico Pluviométrico vinculado no portal Dados APAC. Média diária das estações de Recife e soma por semana epidemiológica. Leituras ausentes não são consideradas chuva zero. Temperatura histórica de apoio via Open-Meteo.",
    atualizacao: "Coleta diária; fonte e data da última coleta no cabeçalho",
    registros: "Somente semanas com sete dias de dados válidos e histórico suficiente",
    variaveis: ["chuva_mm", "condicoes_climaticas"],
  },
  {
    nome: "GeoJSON - Distritos Sanitários (SES-PE)",
    url: "Local",
    tipo: "Dados territoriais",
    descricao:
      "Arquivo GeoJSON com os 8 Distritos Sanitários de Recife e seus 94 bairros. Usado para mapeamento e análise espacial.",
    atualizacao: "Anual",
    registros: "94 bairros / 8 DS",
    variaveis: ["ds", "rpa", "vizinhos_semana_passada"],
  },
  {
    nome: "Lookup de Bairros (bairros_lookup.json)",
    url: "Local",
    tipo: "Dados de referência",
    descricao:
      "Base local com scores de vulnerabilidade territorial e histórico de agravamento por bairro, derivada de análises socioespaciais.",
    atualizacao: "Mensal",
    registros: "94 bairros",
    variaveis: ["vulnerabilidade_territorial", "historico"],
  },
  {
    nome: "Modelos de previsão e validação temporal",
    url: "Local",
    tipo: "Dataset de treinamento",
    descricao:
      "Painel de casos e clima por bairro e semana. Os modelos estimam casos para uma a quatro semanas à frente; métricas e fontes são registradas em forecast_meta.json.",
    atualizacao: "Por treinamento",
    registros: "94 bairros por semana; 18 variáveis por modelo",
    variaveis: [
      "casos", "casos_lag1", "roll4_mean", "chuva_mm", "chuva_roll4",
      "temp_media", "temp_roll4", "vizinhos_ds",
    ],
  },
];

export default function ModalFontesDados({ isOpen, onClose }) {
  const [fonteExpandida, setFonteExpandida] = useState(null);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-titulo">Fontes de Dados do Modelo</h2>
          <button className="modal-fechar" onClick={onClose} aria-label="Fechar">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-intro">
            O modelo de Machine Learning do PULSO utiliza as seguintes fontes de dados
            para treinamento, inferência e priorização territorial:
          </p>

          <div className="fontes-lista">
            {FONTES.map((fonte, i) => {
              const expandida = fonteExpandida === i;
              return (
                <div
                  key={i}
                  className={`fonte-card ${expandida ? "fonte-card--expandida" : ""}`}
                >
                  <div
                    className="fonte-card__header"
                    onClick={() => setFonteExpandida(expandida ? null : i)}
                  >
                    <div className="fonte-card__numero">{i + 1}</div>
                    <div className="fonte-card__info">
                      <div className="fonte-card__nome">{fonte.nome}</div>
                      <div className="fonte-card__meta">
                        <span className="fonte-card__tipo">{fonte.tipo}</span>
                        <span className="fonte-card__atualizacao">
                          Atualização: {fonte.atualizacao}
                        </span>
                      </div>
                    </div>
                    <div className="fonte-card__toggle">
                      {expandida ? "−" : "+"}
                    </div>
                  </div>

                  {expandida && (
                    <div className="fonte-card__body">
                      <p className="fonte-card__descricao">{fonte.descricao}</p>
                      <div className="fonte-card__detalhes">
                        <div className="fonte-card__detalhe">
                          <span className="fonte-card__detalhe-label">URL/Origem:</span>
                          <span className="fonte-card__detalhe-valor">{fonte.url}</span>
                        </div>
                        <div className="fonte-card__detalhe">
                          <span className="fonte-card__detalhe-label">Volume:</span>
                          <span className="fonte-card__detalhe-valor">{fonte.registros}</span>
                        </div>
                      </div>
                      <div className="fonte-card__variaveis">
                        <span className="fonte-card__variaveis-label">Variáveis ML:</span>
                        <div className="fonte-card__variaveis-tags">
                          {fonte.variaveis.map((v) => (
                            <span key={v} className="fonte-card__variavel-tag">
                              {v}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="modal-footer-info">
            <p>
              <strong>Modelo:</strong> XGBoost de contagem |{" "}
              <strong>Variáveis:</strong> 18 |{" "}
              <strong>Saída:</strong> Casos previstos e índice de prioridade (0–100) |{" "}
              <strong>Horizontes:</strong> 1 a 4 semanas
            </p>
            <p style={{ marginTop: 8, fontSize: 12, color: "var(--text-secondary)" }}>
              A coleta das fontes ocorre periodicamente em segundo plano.{" "}
              Se uma coleta falhar, o último conjunto válido é preservado e a interface informa o atraso.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
