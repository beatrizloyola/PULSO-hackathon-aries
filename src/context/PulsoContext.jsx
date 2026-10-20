import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { fetchPrioridade } from "../services/api";
import { SEMANA_PADRAO, HORIZONTE_PADRAO } from "../config";

const PulsoContext = createContext(null);

const DECISAO_SEED = {
  id: "seed-ibura",
  territorio: "Ibura",
  prioridadeNoMomento: 94,
  prioridadeAtual: 61,
  decisao: "Aprovar recomendação",
  observacao: "Inspeção e tratamento de focos realizados nos setores prioritários.",
  timestamp: new Date("2026-06-18T09:12:00").toISOString(),
  resolvida: true,
};

export function PulsoProvider({ children }) {
  const [capacidadeEquipes, setCapacidadeEquipes] = useState(6);
  const [semanaSelecionada, setSemanaSelecionada] = useState(SEMANA_PADRAO);
  const [horizonteSelecionado, setHorizonteSelecionado] = useState(HORIZONTE_PADRAO);
  const [contextoPrevisao, setContextoPrevisao] = useState({ referenciaCod: null, alvoCod: null });
  const [territorioSelecionado, setTerritorioSelecionado] = useState(null);
  const [decisoes, setDecisoes] = useState([DECISAO_SEED]);
  const [telaAtiva, setTelaAtiva] = useState("visao-geral");
  const [territoriosOrdenados, setTerritoriosOrdenados] = useState([]);
  const [apiStatus, setApiStatus] = useState({ loading: true, error: null });
  const [semanasDisponiveis, setSemanasDisponiveis] = useState([]);
  const [dadosStatus, setDadosStatus] = useState(null);
  const [validacao, setValidacao] = useState({});

  // Busca prioridades do backend no mount e a cada mudança de semana/capacidade
  useEffect(() => {
    let cancelled = false;
    let running = false;
    async function load() {
      if (running) return;
      running = true;
      try {
        setApiStatus({ loading: true, error: null });
        const data = await fetchPrioridade({
          semanaId: semanaSelecionada,
          topN: 94,
          capacidade: capacidadeEquipes,
          horizonte: horizonteSelecionado,
        });
        if (cancelled) return;
        // Mapeia resposta da API para formato que as telas esperam
        const mapped = (data.todos || []).map((t) => ({
          nome: t.bairro_nome,
          ds: t.ds,
          rpa: t.rpa,
          score: t.score,
          classificacao: t.classificacao,
          // Componentes brutos para explicabilidade
          tendenciaEpidemiologica: t.componentes?.tendencia_epidemiologica ?? 0,
          condicoesClimaticas: t.componentes?.condicoes_climaticas ?? 0,
          focosIdentificados: t.componentes?.focos_identificados ?? 0,
          vulnerabilidadeTerritorial: t.componentes?.vulnerabilidade_territorial ?? 0,
          historico: t.componentes?.historico ?? 0,
          // Previsão
          casosPrevistos: t.metadados?.casos_previstos ?? 0,
          horizonte: t.metadados?.horizonte ?? 1,
          // Metadados
          casosSemanaAtual: t.metadados?.casos_semana_atual ?? 0,
          casosSemanaAnterior: t.metadados?.casos_semana_anterior ?? 0,
          chuvaAcumuladaMm: t.metadados?.chuva_mm ?? 0,
          tempMedia: t.metadados?.temp_media ?? 0,
          focosAtuais: t.metadados?.focos_atuais ?? 0,
          // Placeholders para compatibilidade
          vulnerabilidade: t.componentes?.vulnerabilidade_territorial >= 70 ? "Alto" : t.componentes?.vulnerabilidade_territorial >= 40 ? "Médio" : "Baixo",
          historicoAgravamento: t.componentes?.historico >= 75,
          setoresPrioritarios: ["Setor 01"],
        }));
        setTerritoriosOrdenados(mapped);
        setSemanasDisponiveis(data.semanas_disponiveis || []);
        setDadosStatus(data.dados || null);
        setValidacao(data.validacao || {});
        setContextoPrevisao({
          referenciaCod: data.semana_cod ?? null,
          alvoCod: data.semana_alvo_cod ?? null,
          horizonte: data.horizonte ?? 1,
        });
        setApiStatus({ loading: false, error: null });
      } catch (e) {
        if (cancelled) return;
        console.error("[PulsoContext] Falha ao carregar prioridades da API:", e);
        setApiStatus({ loading: false, error: e.message });
      } finally {
        running = false;
      }
    }
    load();
    const timer = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [capacidadeEquipes, semanaSelecionada, horizonteSelecionado]);

  const cobertura = useMemo(() => {
    const somaTotal = territoriosOrdenados.reduce((acc, t) => acc + t.score, 0);
    const cobertos = territoriosOrdenados.slice(0, capacidadeEquipes);
    const restante = territoriosOrdenados.slice(capacidadeEquipes);
    const somaCoberta = cobertos.reduce((acc, t) => acc + t.score, 0);
    const percentual = somaTotal > 0 ? Math.round((somaCoberta / somaTotal) * 100) : 0;
    return { cobertos, restante, percentual, somaTotal };
  }, [territoriosOrdenados, capacidadeEquipes]);

  function registrarDecisao({ territorio, prioridadeNoMomento, decisao, observacao }) {
    setDecisoes((prev) => [
      {
        id: `${territorio}-${Date.now()}`,
        territorio,
        prioridadeNoMomento,
        decisao,
        observacao,
        timestamp: new Date().toISOString(),
        resolvida: false,
      },
      ...prev,
    ]);
  }

  function irPara(tela, territorio) {
    if (territorio !== undefined) setTerritorioSelecionado(territorio);
    setTelaAtiva(tela);
  }

  const value = {
    territoriosOrdenados,
    capacidadeEquipes,
    setCapacidadeEquipes,
    semanaSelecionada,
    setSemanaSelecionada,
    horizonteSelecionado,
    setHorizonteSelecionado,
    contextoPrevisao,
    semanasDisponiveis,
    dadosStatus,
    apiStatus,
    validacao,
    territorioSelecionado,
    setTerritorioSelecionado,
    decisoes,
    registrarDecisao,
    telaAtiva,
    setTelaAtiva,
    irPara,
    cobertura,
  };

  return <PulsoContext.Provider value={value}>{children}</PulsoContext.Provider>;
}

export function usePulso() {
  const ctx = useContext(PulsoContext);
  if (!ctx) throw new Error("usePulso deve ser usado dentro de PulsoProvider");
  return ctx;
}
