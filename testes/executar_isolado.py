"""Executa testes/avaliação em cópia descartável, preservando logs e índice reais.

Uso: python -B testes/executar_isolado.py [argumentos pytest]
     python -B testes/executar_isolado.py --metricas
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
from contextlib import ExitStack


def main():
    origem = Path(__file__).resolve().parents[1]
    # Ambiente opcional de desenvolvimento; mantém os pacotes globais existentes.
    pacotes = origem / ".venv" / "Lib" / "site-packages"
    if pacotes.exists():
        sys.path.append(str(pacotes))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["EXECUTION_MODE"] = "mock"
    os.environ["FICDEV_TEST_COPY"] = "1"
    with ExitStack() as stack:
        pasta = stack.enter_context(tempfile.TemporaryDirectory(prefix="ficdev-d02-"))
        stack.callback(os.chdir, origem)
        destino = Path(pasta)
        for nome in ("src", "testes", "dados", "indice", "prompts", "documentacao", "resultados"):
            shutil.copytree(origem / nome, destino / nome, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for nome in ("config.json", "pytest.ini", ".env.example", "README.md", "requirements.txt"):
            shutil.copy2(origem / nome, destino / nome)
        # A validação visual deve usar o mesmo tema da aplicação real.
        config_streamlit = origem / ".streamlit" / "config.toml"
        if config_streamlit.is_file():
            (destino / ".streamlit").mkdir()
            shutil.copy2(config_streamlit, destino / ".streamlit" / "config.toml")
        os.chdir(destino)
        sys.path.insert(0, str(destino))
        # A cópia recebe o índice correspondente ao acervo corrigido, sem tocar
        # no índice do checkout nem reconstruí-lo por troca de provedor.
        from src.embeddings import IndiceVetorial
        from src.ingestion import carregar_acervo_completo
        idx = IndiceVetorial(caminho_indice=None, persistir=False)
        idx.adicionar_chunks(carregar_acervo_completo())
        idx.caminho_indice = "indice/indice_vetorial.json"
        idx.salvar()
        if "--metricas" in sys.argv:
            from src.metrics import AvaliadorDesafio02
            import json
            relatorio = AvaliadorDesafio02().executar_matriz_testes_completa()
            if "--salvar-evidencia" in sys.argv:
                saida = origem / "documentacao" / "evidencias" / "validacao_d02.json"
                saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
                (origem / "resultados" / "metricas" / "relatorio_avaliacao_d02.json").write_text(
                    json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
            resumo = {"total": relatorio["total_testes"], "aprovados": relatorio["aprovados"],
                      "matriz": relatorio["matriz"],
                      "recuperacao": {k: {x: v[x] for x in ("numerador", "denominador", "taxa_acerto")}
                                       for k, v in relatorio["resumo_metricas"]["chunking_recuperacao"].items()
                                       if k in ("config_a", "config_b")},
                      "rag": {k: v for k, v in relatorio["resumo_metricas"]["rag_8_perguntas"].items() if k != "consultas"}}
            print(json.dumps(resumo, ensure_ascii=True, indent=2))
            return 0
        import pytest
        argumentos = sys.argv[1:] or ["testes/", "-v"]
        resultado = pytest.main(argumentos + ["-p", "no:cacheprovider"])
        os.chdir(origem)
        return resultado


if __name__ == "__main__":
    raise SystemExit(main())
