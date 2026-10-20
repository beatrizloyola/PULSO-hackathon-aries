// Cliente HTTP para o backend PULSO (Flask)
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function fetchJSON(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API ${path}: ${resp.status} ${err}`);
  }
  return resp.json();
}

export async function fetchBairros() {
  return fetchJSON("/bairros");
}

export async function fetchPrioridade({ semanaId, topN = 8, capacidade = 3, horizonte = 1 } = {}) {
  return fetchJSON("/prioridade", {
    method: "POST",
    body: JSON.stringify({
      semana_id: semanaId,
      top_n: topN,
      capacidade,
      horizonte,
    }),
  });
}

export async function fetchDetalheBairro(bairroId, semanaId) {
  const qs = semanaId ? `?semana_id=${encodeURIComponent(semanaId)}` : "";
  return fetchJSON(`/prioridade/${bairroId}${qs}`);
}

export async function fetchExplicacao(bairroId, semanaId) {
  return fetchJSON("/prioridade/explicacao", {
    method: "POST",
    body: JSON.stringify({
      bairro_id: bairroId,
      semana_id: semanaId,
    }),
  });
}
