"""python -m scripts.atualizar_dados [--force]. Mesma rotina usada pela API."""
import argparse
import json
import logging

from app.services.data_sync import sync_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Atualizar mesmo antes do prazo de cache")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = sync_data(force=args.force)
    print(json.dumps({k: result.get(k) for k in
                      ("snapshot", "coletado_em", "casos_ate", "chuva_ate", "status")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
