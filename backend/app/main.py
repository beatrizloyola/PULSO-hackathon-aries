import json

from flask import Flask, jsonify, request
from flask_cors import CORS

from app import config
from app.services import model as model_svc
from app.services import forecast_serving, data_sync


# Carregar GeoJSON dos bairros do ESIG (polígonos reais) em memória no startup
GEOJSON_BAIRROS = None
geojson_file = config.DATA_DIR / "bairros_esig.geojson"
if geojson_file.exists():
    with open(geojson_file, "r", encoding="utf-8") as f:
        GEOJSON_BAIRROS = json.load(f)
    features = GEOJSON_BAIRROS.get('features', [])
    print(f"   📍 GeoJSON bairros ESIG carregado: {len(features)} bairros com polígonos reais")
else:
    print("   ⚠️  GeoJSON bairros_esig não encontrado para mapa.")

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

# Startup
print("🚀 [PULSO Backend] Iniciando...")
if not config.BAIRROS_LOOKUP_FILE.exists():
    print("   ⚠️  bairros_lookup.json não encontrado.")
for horizon in config.FORECAST_HORIZONS:
    if not config.forecast_model_file(horizon).exists():
        print(f"   ⚠️  modelo do horizonte {horizon} ausente; execute python -m scripts.train_forecast")
print("✅ [PULSO Backend] Pronto!")
data_sync.start_background_sync()


@app.errorhandler(forecast_serving.DadosIndisponiveis)
def dados_indisponiveis(error):
    return jsonify({"error": str(error)}), 503


@app.errorhandler(ValueError)
def dados_invalidos(error):
    return jsonify({"error": str(error)}), 400

def _to_float(val):
    return float(val) if val is not None else 0.0

def _to_int(val):
    return int(val) if val is not None else 0

@app.route("/health")
def health():
    model_ok = all(config.forecast_model_file(h).exists() for h in config.FORECAST_HORIZONS)
    lookup_ok = config.BAIRROS_LOOKUP_FILE.exists()
    return jsonify({
        "status": "ok" if (model_ok and lookup_ok) else "degraded",
        "modelo_carregado": model_ok,
        "bairros_lookup": lookup_ok,
    })

@app.route("/bairros")
def listar_bairros():
    with open(config.BAIRROS_LOOKUP_FILE, "r", encoding="utf-8") as f:
        bairros = json.load(f)
    return jsonify({"total": len(bairros), "bairros": bairros})

@app.route("/prioridade", methods=["POST"])
def calcular_prioridade():
    req = request.get_json(silent=True) or {}
    semana_id = req.get("semana_id")
    top_n = req.get("top_n", 8)
    capacidade = req.get("capacidade", 3)
    horizonte = int(req.get("horizonte", 1))
    if horizonte not in config.FORECAST_HORIZONS:
        raise ValueError("Horizonte deve estar entre 1 e 4 semanas.")

    df_features, meta = forecast_serving.build_prioridades(semana_id, horizon=horizonte)
    df_features["classificacao"] = df_features["score"].apply(model_svc.classificar_prioridade)

    df_sorted = df_features.sort_values("score", ascending=False).reset_index(drop=True)
    df_sorted["rank"] = df_sorted.index + 1

    top_n = min(int(top_n), len(df_sorted))
    capacidade = min(int(capacidade), len(df_sorted))
    top_df = df_sorted.head(top_n)
    cobertos = df_sorted.head(capacidade)
    restante = df_sorted.iloc[capacidade:]
    soma_total = float(df_sorted["score"].sum())
    soma_coberta = float(cobertos["score"].sum())
    percentual = round((soma_coberta / soma_total * 100), 1) if soma_total > 0 else 0.0

    def row_to_dict(r):
        return {
            "rank": _to_int(r["rank"]),
            "bairro_id": r["bairro_id"],
            "bairro_nome": r["bairro_nome"],
            "ds": r["ds"],
            "rpa": r["rpa"],
            "score": _to_float(r["score"]),
            "classificacao": r["classificacao"],
            "componentes": {
                "tendencia_epidemiologica": _to_float(r["tendencia_epidemiologica"]),
                "condicoes_climaticas": _to_float(r["condicoes_climaticas"]),
                "focos_identificados": _to_float(r["focos_identificados"]),
                "vulnerabilidade_territorial": _to_float(r["vulnerabilidade_territorial"]),
                "historico": _to_float(r["historico"]),
            },
            "metadados": {
                "casos_previstos": _to_float(r["casos_previstos"]),
                "horizonte": _to_int(r["horizonte"]),
                "casos_semana_atual": _to_int(r["casos_semana_atual"]),
                "casos_semana_anterior": _to_int(r["casos_semana_anterior"]),
                "chuva_mm": _to_float(r["chuva_mm"]),
                "temp_media": _to_float(r["temp_media"]),
                "focos_atuais": _to_int(r["focos_atuais"]),
            },
        }

    return jsonify({
        "semana_id": f"{meta['semana_cod'] // 100}-W{meta['semana_cod'] % 100:02d}",
        "semanas_disponiveis": meta["semanas_disponiveis"],
        "dados": meta["dados"],
        "fontes": {"clima": meta["fonte_clima"], "casos": meta["fonte_casos"]},
        "validacao": data_sync.read_json(config.FORECAST_META_FILE).get("backtest", {}).get("metrics", {}),
        "semana_cod": meta["semana_cod"],
        "semana_alvo_cod": meta["semana_alvo_cod"],
        "horizonte": meta["horizonte"],
        "total_bairros": len(df_sorted),
        "top_n": top_n,
        "capacidade": capacidade,
        "cobertura_percentual": float(percentual),
        "top_prioridades": [row_to_dict(r) for _, r in top_df.iterrows()],
        "todos": [row_to_dict(r) for _, r in df_sorted.iterrows()],
        "cobertos": [row_to_dict(r) for _, r in cobertos.iterrows()],
        "restante": [row_to_dict(r) for _, r in restante.iterrows()],
    })

@app.route("/prioridade/<bairro_id>")
def detalhe_bairro(bairro_id):
    semana_id = request.args.get("semana_id")
    horizonte = int(request.args.get("horizonte", 1))
    df_features, _ = forecast_serving.build_prioridades(semana_id, horizon=horizonte)
    row = df_features[df_features["bairro_id"] == bairro_id]
    if row.empty:
        return jsonify({"error": "Bairro não encontrado"}), 404

    r = row.iloc[0]
    score = _to_float(r["score"])
    return jsonify({
        "bairro_id": bairro_id,
        "bairro_nome": r["bairro_nome"],
        "ds": r["ds"],
        "rpa": r["rpa"],
        "score": score,
        "classificacao": model_svc.classificar_prioridade(score),
        "componentes": {
            "tendencia_epidemiologica": _to_float(r["tendencia_epidemiologica"]),
            "condicoes_climaticas": _to_float(r["condicoes_climaticas"]),
            "focos_identificados": _to_float(r["focos_identificados"]),
            "vulnerabilidade_territorial": _to_float(r["vulnerabilidade_territorial"]),
            "historico": _to_float(r["historico"]),
        },
        "metadados": {
            "casos_previstos": _to_float(r["casos_previstos"]),
            "horizonte": _to_int(r["horizonte"]),
            "casos_semana_atual": _to_int(r["casos_semana_atual"]),
            "casos_semana_anterior": _to_int(r["casos_semana_anterior"]),
            "chuva_mm": _to_float(r["chuva_mm"]),
            "temp_media": _to_float(r["temp_media"]),
            "focos_atuais": _to_int(r["focos_atuais"]),
        },
    })

@app.route("/prioridade/explicacao", methods=["POST"])
def explicacao():
    req = request.get_json(silent=True) or {}
    bairro_id = req.get("bairro_id")
    semana_id = req.get("semana_id")
    horizonte = int(req.get("horizonte", 1))
    df_features, meta = forecast_serving.build_prioridades(semana_id, horizon=horizonte)
    result = model_svc.explain_forecast(bairro_id, df_features, horizonte)
    if "error" in result:
        return jsonify(result), 404
    return jsonify({**result, "semana_cod": meta["semana_cod"], "dados": meta["dados"]})

@app.route("/mapa")
def mapa_prioridade():
    """Retorna GeoJSON dos bairros (ZEIS como polígonos, non-ZEIS como pontos) com scores."""
    if GEOJSON_BAIRROS is None:
        return jsonify({"error": "GeoJSON não disponível"}), 503
    
    semana_id = request.args.get("semana_id")
    horizonte = int(request.args.get("horizonte", 1))
    df_features, _ = forecast_serving.build_prioridades(semana_id, horizon=horizonte)
    df_features["classificacao"] = df_features["score"].apply(model_svc.classificar_prioridade)
    
    # Criar lookup bairro -> score (case-insensitive)
    bairro_scores = {}
    for _, row in df_features.iterrows():
        bairro_scores[row["bairro_nome"].upper().strip()] = {
            "score": _to_float(row["score"]),
            "classificacao": row["classificacao"],
            "ds": row["ds"],
        }
    
    # Clonar GeoJSON e adicionar propriedades
    import copy
    geojson = copy.deepcopy(GEOJSON_BAIRROS)
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        # ESIG GeoJSON usa EBAIRRNOME como nome do bairro
        bairro_nome = (props.get("EBAIRRNOME") or props.get("bairro", "")).upper().strip()
        if bairro_nome in bairro_scores:
            info = bairro_scores[bairro_nome]
            props["score"] = info["score"]
            props["classificacao"] = info["classificacao"]["rotulo"]
            props["classificacao_chave"] = info["classificacao"]["chave"]
            props["ds"] = info["ds"]
            props["bairro"] = bairro_nome  # Manter UPPERCASE consistente com /prioridade
        else:
            props["score"] = 0
            props["classificacao"] = "Desconhecido"
            props["classificacao_chave"] = "baixo"
            props["ds"] = "?"
            props["bairro"] = bairro_nome
    
    return jsonify(geojson)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
