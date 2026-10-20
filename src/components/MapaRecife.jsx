import { useEffect, useState } from "react";
import { MapContainer, TileLayer, GeoJSON } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { usePulso } from "../context/PulsoContext";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function getColor(score) {
  if (score >= 85) return "#ef4444"; // Crítico - vermelho
  if (score >= 70) return "#f97316"; // Alto - laranja
  if (score >= 50) return "#eab308"; // Moderado - amarelo
  return "#22c55e"; // Baixo - verde
}

function styleFeature(feature) {
  const score = feature?.properties?.score ?? 0;
  return {
    fillColor: getColor(score),
    weight: 2,
    opacity: 1,
    color: "#fff",
    dashArray: "3",
    fillOpacity: 0.7,
  };
}

export default function MapaRecife({ onBairroClick }) {
  const { contextoPrevisao, dadosStatus } = usePulso();
  const { referenciaCod, alvoCod } = contextoPrevisao;
  const coletadoEm = dadosStatus?.coletado_em;
  const [geojson, setGeojson] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!referenciaCod || !alvoCod) return;
    let cancelled = false;
    setLoading(true);
    const qs = new URLSearchParams({
      semana_id: `${Math.floor(referenciaCod / 100)}-W${String(referenciaCod % 100).padStart(2, "0")}`,
      horizonte: String(contextoPrevisao.horizonte),
    });
    fetch(`${API_BASE}/mapa?${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Falha no mapa: ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setGeojson(data);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("[MapaRecife] Erro ao carregar GeoJSON:", err);
        setGeojson(null);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [referenciaCod, alvoCod, contextoPrevisao.horizonte, coletadoEm]);

  if (loading) {
    return <div className="mapa-loading">Carregando mapa...</div>;
  }

  if (!geojson || !geojson.features) {
    return <div className="mapa-loading">Mapa indisponível</div>;
  }

  return (
    <div className="mapa-container">
      <MapContainer
        center={[-8.05, -34.9]}
        zoom={12}
        scrollWheelZoom={false}
        style={{ height: "100%", width: "100%", borderRadius: 8 }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <GeoJSON
          key={`${referenciaCod}-${alvoCod}-${coletadoEm}`}
          data={geojson}
          style={styleFeature}
          onEachFeature={(feature, layer) => {
            const props = feature.properties || {};
            const nome = props.bairro || "Bairro";
            const score = props.score ?? 0;
            const classificacao = props.classificacao || "Desconhecido";
            const ds = props.ds || "";
            layer.bindTooltip(
              `<strong>${nome}</strong><br/>DS ${ds} — Score: ${score}/100<br/>${classificacao}`,
              { direction: "top", sticky: true }
            );
            layer.on("click", () => {
              if (onBairroClick) onBairroClick(nome);
            });
          }}
        />
      </MapContainer>
      <div className="mapa-legenda">
        <div className="legenda-titulo">Prioridade dos Bairros</div>
        <div className="legenda-item">
          <span className="legenda-cor" style={{ background: "#ef4444" }} />
          <span>Crítico (≥85)</span>
        </div>
        <div className="legenda-item">
          <span className="legenda-cor" style={{ background: "#f97316" }} />
          <span>Alto (70-84)</span>
        </div>
        <div className="legenda-item">
          <span className="legenda-cor" style={{ background: "#eab308" }} />
          <span>Moderado (50-69)</span>
        </div>
        <div className="legenda-item">
          <span className="legenda-cor" style={{ background: "#22c55e" }} />
          <span>Baixo (&lt;50)</span>
        </div>
      </div>
    </div>
  );
}
