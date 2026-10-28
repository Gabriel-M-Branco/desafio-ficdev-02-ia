"""Executor Windows isolado de desenvolvimento; NÃO substitui autenticação real.

Não inicia servidor, não altera dependências FastAPI e não aprova/publica imagens.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from datetime import datetime

from src import resolver_caminho


def identidade_windows():
    if os.name != "nt":
        raise RuntimeError("Teste local exclusivo para sessão Windows.")
    executavel = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/whoami.exe"
    resposta = subprocess.run([str(executavel), "/user", "/fo", "csv", "/nh"],
                              capture_output=True, check=True, timeout=10)
    # whoami devolve usuário/SID do token do processo, nunca campos do cliente.
    linha = next(csv.reader(io.StringIO(resposta.stdout.decode("utf-8", errors="replace"))))
    if len(linha) != 2 or not linha[0].strip() or not re.fullmatch(r"S-1-\d+(?:-\d+)+", linha[1]):
        raise RuntimeError("Não foi possível verificar a identidade Windows.")
    return {"usuario": linha[0], "sid": linha[1], "origem": "token_sessao_windows"}


def gerar_teste_local(ativar=False, gerar_uma=False):
    if not ativar or not gerar_uma:
        raise RuntimeError("Desativado: exija --modo-local e --gerar-uma explicitamente.")
    identidade = identidade_windows()
    from src.audit import AuditLogger
    from src.image_generation import ImageGenerator
    # Seleção restrita a este executor; não modifica .env nem a aplicação normal.
    anterior = os.environ.get("IMAGE_PROVIDER")
    os.environ["IMAGE_PROVIDER"] = "cloudflare"
    try:
        gerador = ImageGenerator()
    finally:
        if anterior is None:
            os.environ.pop("IMAGE_PROVIDER", None)
        else:
            os.environ["IMAGE_PROVIDER"] = anterior
    if gerador.image_provider != "cloudflare":
        raise RuntimeError("Configure IMAGE_PROVIDER=cloudflare; nenhum fallback será usado.")
    raiz = resolver_caminho(".rf10-testes-locais") / uuid.uuid4().hex
    gerador.output_dir = raiz / "imagens"
    gerador.output_dir.mkdir(parents=True, exist_ok=False)
    logger = AuditLogger(str(raiz / "logs"))
    contexto = {"ambiente": "teste_local_nao_producao", "identidade_local": identidade,
                "substitui_autenticacao_real": False, "publicacao_permitida": False}
    resultado = gerador.gerar_comunicado_oficial(
        titulo="COMUNICADO OFICIAL: MATRÍCULAS E INGRESSO EM ESCOLA TÉCNICA",
        nome_arquivo="teste_local_rf10.png", audit_logger=logger)
    if not resultado["sucesso"]:
        return {"sucesso": False, "codigo_erro": resultado.get("codigo_erro"),
                "identidade_local": identidade, "id_execucao": resultado.get("id_execucao")}
    imagem = resolver_caminho(resultado["caminho_imagem"])
    sha = hashlib.sha256(imagem.read_bytes()).hexdigest()
    if sha != resultado["metadados"]["sha256_imagem"]:
        raise RuntimeError("Hash da imagem diverge; validação interrompida.")
    pendencia = {**contexto, "id_execucao_geracao": resultado["id_execucao"],
                 "arquivo_imagem": resultado["caminho_imagem"], "sha256_imagem": sha,
                 "status": "pendente_revisao", "revisao_humana_obrigatoria": True,
                 "data": datetime.now().astimezone().isoformat()}
    decisoes = raiz / "decisoes"
    decisoes.mkdir()
    arquivo = decisoes / "revisao_pendente.json"
    arquivo.write_text(json.dumps(pendencia, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.registrar_execucao(modalidade="imagem_contexto_teste", arquivo_origem=str(imagem),
        provedor="sessao_windows_local", modelo="nao_aplicavel", versao_prompt="teste_local",
        parametros=contexto, resultado=pendencia, duracao_segundos=0)
    return {"sucesso": True, **pendencia, "caminho_metadados": resultado["caminho_metadados"],
            "arquivo_pendencia": str(arquivo), "diretorio_logs": str(logger.log_dir),
            "tempo_processamento_segundos": resultado["metadados"]["tempo_processamento_segundos"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo-local", action="store_true")
    parser.add_argument("--gerar-uma", action="store_true", help="Autoriza uma geração Cloudflare (cota/créditos).")
    args = parser.parse_args()
    try:
        resultado = gerar_teste_local(args.modo_local, args.gerar_uma)
    except Exception as exc:
        # Nunca imprimir exceções externas que possam conter credenciais.
        print(json.dumps({"sucesso": False, "erro_tipo": type(exc).__name__}))
        raise SystemExit(1)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado["sucesso"] else 1)


if __name__ == "__main__":
    main()
