// O backend resolve a última semana com cobertura suficiente nas fontes.
export const SEMANA_PADRAO = "";

// Horizontes de previsão (semanas à frente) e skill medido no backtest
// (precisão@10 vs baseline de persistência). Serve para a UI mostrar
// honestamente até onde confiar em cada horizonte.
// Formata um código de semana epidemiológica YYYYWW -> "semana NN/YYYY".
export function formatSemana(cod) {
  if (!cod) return "—";
  const ano = Math.floor(cod / 100);
  const semana = String(cod % 100).padStart(2, "0");
  return `semana ${semana}/${ano}`;
}

export const HORIZONTE_PADRAO = 1;
export const HORIZONTES = [
  { valor: 1, label: "próxima semana" },
  { valor: 2, label: "2 semanas" },
  { valor: 3, label: "3 semanas" },
  { valor: 4, label: "4 semanas" },
];
