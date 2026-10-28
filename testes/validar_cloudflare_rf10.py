"""Validação manual: exatamente uma tentativa real, somente com --gerar-uma."""
import argparse
import json
import os
import uuid

TITULO = "COMUNICADO OFICIAL: MATRÍCULAS E INGRESSO EM ESCOLA TÉCNICA"


def main():
    parser = argparse.ArgumentParser(description="Uma geração real Cloudflare; pode consumir cota/créditos.")
    parser.add_argument("--gerar-uma", action="store_true", help="Autoriza uma única requisição de geração real")
    parser.add_argument("--prever", action="store_true", help="Mostra prompt, parâmetros e caminhos; não executa inferência")
    args = parser.parse_args()
    if not args.gerar_uma and not args.prever:
        parser.error("Nenhuma geração executada. Use --gerar-uma explicitamente para consumir uma geração.")
    # Importar o módulo carrega .env sem imprimir as credenciais.
    from src.image_generation import ImageGenerator
    os.environ["IMAGE_PROVIDER"] = "cloudflare"
    os.environ["EXECUTION_MODE"] = "api"
    gerador = ImageGenerator()
    nome = f"validacao_cloudflare_rf10_educacional_{uuid.uuid4().hex}.png"
    if args.prever:
        caminho = gerador.output_dir / nome
        print(json.dumps({"prompt": gerador.construir_prompt_estruturado(TITULO)["prompt_completo_en"],
                          "modelo": gerador.image_model, "parametros": gerador.image_params,
                          "timeout_seconds": gerador.image_timeout,
                          "imagem": str(caminho),
                          "arte_ia": str(caminho.with_name(caminho.stem + "_arte_ia.png")),
                          "metadados": str(caminho.with_suffix(".json"))}, ensure_ascii=False, indent=2))
        return
    resultado = gerador.gerar_comunicado_oficial(titulo=TITULO, nome_arquivo=nome)
    campos = ["sucesso", "caminho_imagem", "caminho_metadados", "id_execucao", "codigo_erro", "erro"]
    print(json.dumps({k: resultado[k] for k in campos if k in resultado}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado["sucesso"] else 1)


if __name__ == "__main__":
    main()
