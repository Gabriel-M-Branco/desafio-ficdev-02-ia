"""Cloudflare RF10: somente respostas simuladas; nunca consome cota."""
import base64
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from PIL import Image

from src.image_generation import ImageGenerator
from src import resolver_caminho
from src.web_files import arquivo_publico


@pytest.fixture
def cloudflare(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setenv("EXECUTION_MODE", "api")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token-teste-secreto")
    monkeypatch.setenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.delenv("IMAGE_ENDPOINT", raising=False)
    gerador = ImageGenerator()
    gerador.output_dir = tmp_path
    gerador.config["paths"]["resultados_logs"] = str(tmp_path / "logs")
    png = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(png, format="PNG")
    resposta = Mock(status_code=200, headers={"Content-Type": "application/json"})
    resposta.json.return_value = {"success": True, "result": {"image": base64.b64encode(png.getvalue()).decode()}}
    post = Mock(return_value=resposta)
    monkeypatch.setattr(requests, "post", post)
    return gerador, post, resposta, png.getvalue()


@pytest.mark.parametrize("formato", ["base64", "data_uri", "binario", "direto"])
def test_resposta_imagem_e_contrato_completo(cloudflare, formato):
    gerador, post, resposta, png = cloudflare
    if formato == "data_uri":
        resposta.json.return_value["result"]["image"] = "data:image/png;base64," + base64.b64encode(png).decode()
    elif formato == "binario":
        resposta.headers = {"Content-Type": "image/png"}
        resposta.content = png
    elif formato == "direto":
        resposta.json.return_value = {"image": base64.b64encode(png).decode()}
    resultado = gerador.gerar_comunicado_oficial()
    assert resultado["sucesso"]
    assert post.call_count == 1
    args, kwargs = post.call_args
    assert args[0] == "https://api.cloudflare.com/client/v4/accounts/" + "a" * 32 + "/ai/run/@cf/black-forest-labs/flux-1-schnell"
    assert kwargs["headers"]["Authorization"] == "Bearer cf-token-teste-secreto"
    assert set(kwargs["json"]) == {"prompt", "steps"}
    assert kwargs["timeout"] == 60 and not kwargs["allow_redirects"]
    meta = resultado["metadados"]
    assert meta["provedor_efetivo"] == "cloudflare"
    assert meta["modelo_ia_utilizado"] == "@cf/black-forest-labs/flux-1-schnell"
    assert meta["parametros_geracao"] == {"steps": 4}
    assert meta["estado_imagem"] == "pendente_revisao"
    assert len(meta["sha256_imagem"]) == 64
    persistido = resolver_caminho(resultado["caminho_metadados"]).read_text(encoding="utf-8")
    registro = (gerador.output_dir / "logs" / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8")
    assert "cf-token-teste-secreto" not in persistido + registro


@pytest.mark.parametrize("status,cf_code,codigo", [
    (401, 10000, "autenticacao"), (403, 10000, "autenticacao"),
    (429, 3036, "cota_gratuita_esgotada"), (429, 3040, "indisponibilidade"),
    (429, 9999, "limite_requisicoes"), (503, 9999, "indisponibilidade"),
    (403, 5035, "cobranca_ou_creditos"), (408, 3007, "timeout"),
    (200, 3036, "cota_gratuita_esgotada")])
def test_erros_sem_retry_sem_credenciais(cloudflare, status, cf_code, codigo):
    gerador, post, resposta, _ = cloudflare
    resposta.status_code = status
    resposta.json.return_value = {"success": False, "errors": [{"code": cf_code, "message": "falha cf-token-teste-secreto"}]}
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"] and resultado["codigo_erro"] == codigo
    assert resultado["metadados"]["erro"]["codigos_provedor"] == [str(cf_code)]
    assert post.call_count == 1
    assert not list(gerador.output_dir.glob("*.png"))
    arquivos = list(gerador.output_dir.rglob("*.json"))
    assert arquivos
    assert all("cf-token-teste-secreto" not in p.read_text(encoding="utf-8") for p in arquivos)


@pytest.mark.parametrize("tipo", ["timeout", "conexao"])
def test_falha_transporte(cloudflare, tipo):
    gerador, post, _, _ = cloudflare
    post.side_effect = requests.Timeout() if tipo == "timeout" else requests.ConnectionError()
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"]
    assert post.call_count == 1
    assert resultado["codigo_erro"] == ("timeout" if tipo == "timeout" else "indisponibilidade")
    assert resultado["erro"]


@pytest.mark.parametrize("tipo", ["token", "conta", "mock", "modelo", "steps"])
def test_validacao_antes_da_api(cloudflare, monkeypatch, tipo):
    gerador, post, _, _ = cloudflare
    if tipo == "token": monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    elif tipo == "conta": monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "")
    elif tipo == "mock": monkeypatch.setenv("EXECUTION_MODE", "mock")
    elif tipo == "modelo": gerador.image_model = "../../invalido"
    else: gerador.image_params["steps"] = 20
    assert not gerador.gerar_comunicado_oficial()["sucesso"]
    post.assert_not_called()


@pytest.mark.parametrize("tipo", ["vazio", "base64", "imagem", "json"])
def test_resposta_invalida_nao_gera_imagem_falsa(cloudflare, tipo):
    gerador, _, resposta, _ = cloudflare
    if tipo == "vazio": resposta.json.return_value = {"success": True, "result": {}}
    elif tipo == "base64": resposta.json.return_value = {"image": "%%%"}
    elif tipo == "imagem": resposta.json.return_value = {"image": base64.b64encode(b"nao imagem").decode()}
    else: resposta.json.side_effect = ValueError()
    assert not gerador.gerar_comunicado_oficial()["sucesso"]
    assert not list(gerador.output_dir.glob("*.png"))


@pytest.mark.parametrize("path", [".env", ".git/config", "src/main.py", "config.json", "resultados/../.env", "dados/processados/.env"])
def test_segredos_nao_sao_downloads_publicos(tmp_path, path):
    assert not arquivo_publico(tmp_path, path)


@pytest.mark.parametrize("path", ["resultados/audios/teste.wav", "resultados/minutas/teste.pdf"])
def test_downloads_existentes_preservados(tmp_path, path):
    assert arquivo_publico(tmp_path, path)


@pytest.mark.parametrize("path", ["dados/originais/brasao.png", "dados/originais/entrada_audio.mp3",
                                 "dados/processados/extracao.json", "resultados/logs/audit_trail.jsonl"])
def test_fontes_e_logs_nao_sao_downloads_publicos(tmp_path, path):
    assert not arquivo_publico(tmp_path, path)


def test_validador_real_exige_comando_explicito(monkeypatch):
    import sys
    from testes.validar_cloudflare_rf10 import main
    monkeypatch.setattr(sys, "argv", ["validar_cloudflare_rf10"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_cenario_educacional_prompt_exato_na_cloudflare(cloudflare):
    from testes.validar_cloudflare_rf10 import TITULO
    gerador, post, _, _ = cloudflare
    resultado = gerador.gerar_comunicado_oficial(titulo=TITULO)
    assert resultado["sucesso"]
    assert post.call_args.kwargs["json"]["prompt"] == resultado["metadados"]["prompt_estruturado"]["prompt_completo_en"]
    assert post.call_args.kwargs["json"]["steps"] == 4


def test_previa_nunca_gera_mesmo_com_flag_real(monkeypatch, capsys, tmp_path):
    import sys
    import src.image_generation as modulo
    from testes.validar_cloudflare_rf10 import main
    gerador = Mock()
    gerador.output_dir = tmp_path
    gerador.image_model = "@cf/black-forest-labs/flux-1-schnell"
    gerador.image_params = {"steps": 4}
    gerador.image_timeout = 60
    gerador.construir_prompt_estruturado.return_value = {"prompt_completo_en": "educational preview"}
    monkeypatch.setattr(modulo, "ImageGenerator", Mock(return_value=gerador))
    monkeypatch.setattr(sys, "argv", ["validar_cloudflare_rf10", "--prever", "--gerar-uma"])
    main()
    previa = json.loads(capsys.readouterr().out)
    assert previa["prompt"] == "educational preview"
    assert "educacional_" in previa["imagem"]
    gerador.gerar_comunicado_oficial.assert_not_called()


def test_validador_real_solicita_so_uma_geracao(monkeypatch, capsys):
    import sys
    from testes.validar_cloudflare_rf10 import main
    monkeypatch.setenv("IMAGE_PROVIDER", "fal-ai")
    monkeypatch.setenv("EXECUTION_MODE", "mock")
    import src.image_generation as modulo
    gerador = Mock()
    gerador.gerar_comunicado_oficial.return_value = {"sucesso": True}
    monkeypatch.setattr(modulo, "ImageGenerator", Mock(return_value=gerador))
    monkeypatch.setattr(sys, "argv", ["validar_cloudflare_rf10", "--gerar-uma"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    gerador.gerar_comunicado_oficial.assert_called_once()
    assert json.loads(capsys.readouterr().out)["sucesso"]
