import { useState, useEffect } from "react";

const SECOES = [
  {
    id: "visao-geral", titulo: "Como a prioridade é calculada",
    conteudo: `O PULSO estima casos de dengue por bairro para uma a quatro semanas à frente, com modelos XGBoost. Os casos previstos são convertidos em um índice de 0 a 100 pela expressão 100 × casos / (casos + 5).

O sistema apoia a distribuição das equipes disponíveis. As classificações e recomendações são referências do protótipo; a decisão permanece com a equipe de vigilância.`
  },
  {
    id: "origem-dados", titulo: "Fontes e atualização",
    conteudo: `**Chuva — APAC**
O Histórico Pluviométrico está vinculado no portal http://dados.apac.pe.gov.br:41120/dadosApac/. A coleta consulta Recife e preserva as leituras por estação e data. Calcula a média diária das estações com leitura válida e soma os sete dias da semana. Um traço na tabela representa ausência de leitura, não chuva zero. O valor municipal é compartilhado pelos bairros; não é uma medição individual de cada bairro.

**Temperatura — Open-Meteo**
Temperaturas diárias são agregadas na mesma semana. Essa fonte é identificada separadamente da APAC.

**Casos — SINAN / Dados Abertos do Recife**
Os arquivos anuais disponíveis são consultados no catálogo. As notificações de Recife são agregadas por bairro e semana, a partir da data de notificação.

A coleta ocorre em segundo plano, diariamente por padrão. O cabeçalho informa a última coleta e eventuais atrasos. Em caso de falha, o sistema preserva o último conjunto válido.`
  },
  {
    id: "periodo", titulo: "Período da previsão",
    conteudo: `A seleção automática usa a última semana com sete dias de clima válido, cobertura de notificações e histórico suficiente para as variáveis das quatro semanas anteriores. Uma semana com dados climáticos ausentes não é preenchida artificialmente com zero.

O clima mais recente não adianta a previsão quando ainda faltam casos do mesmo período. A data de referência e a semana prevista ficam visíveis no cabeçalho. A cobertura do SINAN é estimada conservadoramente pela última data de notificação publicada; isso não garante que todos os casos já tenham sido notificados.`
  },
  {
    id: "modelo", titulo: "Modelo e validação",
    conteudo: `Cada horizonte usa 18 variáveis: casos recentes, médias e tendências, chuva e temperatura atuais e defasadas, sazonalidade, atributos territoriais e casos dos demais bairros do mesmo distrito sanitário.

Os modelos usam objetivo de contagem Poisson. A validação temporal compara erro absoluto médio e precisão dos dez bairros prioritários com uma previsão que repete os casos da semana de referência. A precisão@10 exibida no seletor vem das métricas do modelo salvo e não representa probabilidade individual de acerto.

Atualizar os dados de entrada não retreina automaticamente o modelo. Um novo treinamento exige reavaliar essas métricas antes de substituir os modelos.

Os componentes exibidos nas telas resumem sinais epidemiológicos e climáticos. Focos identificados são um indicador indireto baseado em casos, não uma contagem de inspeções de campo.`
  },
];

export default function ModalAlgoritmo({ isOpen, onClose }) {
  const [secaoAtiva, setSecaoAtiva] = useState(SECOES[0].id);

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

  const secaoAtual = SECOES.find((s) => s.id === secaoAtiva);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container modal-container--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-titulo">Como funciona o Algoritmo PULSO</h2>
          <button className="modal-fechar" onClick={onClose} aria-label="Fechar">
            ✕
          </button>
        </div>

        <div className="modal-body modal-body--split">
          {/* Menu lateral */}
          <div className="algo-menu">
            {SECOES.map((secao) => (
              <button
                key={secao.id}
                className={`algo-menu__item ${secaoAtiva === secao.id ? "algo-menu__item--ativo" : ""}`}
                onClick={() => setSecaoAtiva(secao.id)}
              >
                {secao.titulo}
              </button>
            ))}
          </div>

          {/* Conteúdo */}
          <div className="algo-conteudo">
            <h3 className="algo-conteudo__titulo">{secaoAtual.titulo}</h3>
            <div className="algo-conteudo__texto">
              {secaoAtual.conteudo.split("\n").map((linha, i) => {
                if (linha.startsWith("**") && linha.endsWith("**")) {
                  return (
                    <h4 key={i} className="algo-conteudo__subtitulo">
                      {linha.replace(/\*\*/g, "")}
                    </h4>
                  );
                }
                if (linha.startsWith("• ")) {
                  return (
                    <div key={i} className="algo-conteudo__item">
                      <span className="algo-conteudo__bullet">•</span>
                      <span>{linha.replace("• ", "")}</span>
                    </div>
                  );
                }
                if (linha.trim() === "") {
                  return <div key={i} style={{ height: 8 }} />;
                }
                return (
                  <p key={i} className="algo-conteudo__paragrafo">
                    {linha.replace(/\*\*/g, "")}
                  </p>
                );
              })}
            </div>
          </div>
        </div>

        <div className="modal-footer-info" style={{ padding: "16px 24px", marginTop: 0, borderTop: "1px solid var(--border)" }}>
          <strong>PULSO v1.0</strong> — XGBoost Regressor | 8 features | 94 territórios | MAE 4.04 | R² 0.87
        </div>
      </div>
    </div>
  );
}
