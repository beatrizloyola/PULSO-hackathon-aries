import { usePulso } from "../context/PulsoContext";
import { HORIZONTES, formatSemana } from "../config";

const TITULOS = {
  "visao-geral": "Central de Priorização Territorial",
  prioridades: "Prioridades de Intervenção",
  explicacao: "Explicação da Prioridade",
  recomendacao: "Ação Recomendada",
  planejamento: "Planejamento de Capacidade Operacional",
  "acoes-resultados": "Ações e Resultados",
};

export default function Header() {
  const {
    telaAtiva, territorioSelecionado,
    semanaSelecionada, setSemanaSelecionada,
    horizonteSelecionado, setHorizonteSelecionado,
    contextoPrevisao, semanasDisponiveis, dadosStatus, apiStatus, validacao,
  } = usePulso();
  const titulo = TITULOS[telaAtiva] ?? "PULSO";
  const semanas = [...semanasDisponiveis].reverse().map((cod) => ({
    id: `${Math.floor(cod / 100)}-W${String(cod % 100).padStart(2, "0")}`,
    label: formatSemana(cod),
  }));

  // Breadcrumb: nas telas de dados, mostra explicitamente O QUE está sendo
  // previsto (semana-alvo) e A PARTIR DE QUAL dado (semana de referência).
  const { referenciaCod, alvoCod } = contextoPrevisao;
  let breadcrumb = referenciaCod
    ? `Prevendo a ${formatSemana(alvoCod)} · a partir dos dados até a ${formatSemana(referenciaCod)}`
    : "Vigilância epidemiológica de dengue";
  if (telaAtiva === "explicacao" && territorioSelecionado) {
    breadcrumb = `Prioridades / ${territorioSelecionado}`;
  } else if (telaAtiva === "recomendacao" && territorioSelecionado) {
    breadcrumb = `Prioridades / ${territorioSelecionado} / Recomendação`;
  }

  return (
    <>
    <header className="app-header">
      <div className="app-header__left">
        <h1>{titulo}</h1>
        <div className="app-header__breadcrumb">{breadcrumb}</div>
      </div>
      <div className="app-header__right">
        <label className="app-header__semana">
          <span className="app-header__semana-label">Dados até a semana</span>
          <select
            className="app-header__semana-select"
            value={semanaSelecionada}
            onChange={(e) => setSemanaSelecionada(e.target.value)}
          >
            <option value="">Última disponível</option>
            {semanas.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="app-header__semana">
          <span className="app-header__semana-label">Prever à frente</span>
          <select
            className="app-header__semana-select"
            value={horizonteSelecionado}
            onChange={(e) => setHorizonteSelecionado(Number(e.target.value))}
          >
            {HORIZONTES.map((h) => (
              <option key={h.valor} value={h.valor}>
                {h.label}
                {validacao[`h${h.valor}`]?.precisao_k_xgb != null
                  ? ` · precisão@10 ${Math.round(validacao[`h${h.valor}`].precisao_k_xgb * 100)}%`
                  : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="app-header__avatar">RS</div>
      </div>
    </header>
    <div className={`dados-status${dadosStatus?.desatualizados || apiStatus.error ? " dados-status--aviso" : ""}`} role="status">
      <div>
        Chuva: <a href="http://dados.apac.pe.gov.br:41120/dadosApac/" target="_blank" rel="noreferrer">APAC</a>
        {" · Temperatura: Open-Meteo · Casos: SINAN/Recife"}
        {dadosStatus?.coletado_em && ` · Coleta: ${new Date(dadosStatus.coletado_em).toLocaleString("pt-BR", { timeZone: "America/Recife" })}`}
      </div>
      {dadosStatus?.casos_ate && <div>
        {`Cobertura publicada: chuva até ${dadosStatus.chuva_ate?.split("-").reverse().join("/") || "—"} · notificações até ${dadosStatus.casos_ate.split("-").reverse().join("/")}`}
      </div>}
      {apiStatus.loading && <div>Consultando dados disponíveis…</div>}
      {apiStatus.error && <div>Não foi possível atualizar a previsão: {apiStatus.error}</div>}
      {dadosStatus?.avisos?.map((aviso) => <div key={aviso}>{aviso}</div>)}
    </div>
    </>
  );
}
