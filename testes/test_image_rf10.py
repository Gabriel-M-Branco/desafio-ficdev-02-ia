"""RF10 offline: geração HF simulada, composição/persistência/auditoria reais."""
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.image_generation import ImageGenerator
from src import resolver_caminho


def test_correcao_placa_preserva_pixels_externos_e_original(geracao):
    from PIL import ImageChops
    gerador, cliente, _, _ = geracao
    original = Image.new("RGB", (1080, 1350), "white")
    antes = original.tobytes()
    regiao = (152, 374, 940, 478)
    corrigida = gerador.corrigir_placa_composicao(original, regiao, (33, 80, 130))
    assert original.tobytes() == antes
    assert ImageChops.difference(original, corrigida).getbbox() == regiao
    assert len(corrigida.crop(regiao).getcolors(10000)) > 1
    cliente.text_to_image.assert_not_called()


def test_correcao_placa_rejeita_regiao_invalida(geracao):
    gerador, _, _, _ = geracao
    with pytest.raises(ValueError):
        gerador.corrigir_placa_composicao(Image.new("RGB", (10, 10)), (-1, 0, 20, 10), "blue")


def test_prompt_enviado_identico_aos_campos_e_metadados(geracao):
    gerador, cliente, _, _ = geracao
    titulo = "MATRÍCULAS: EDUCAÇÃO E INSCRIÇÕES"
    resultado = gerador.gerar_comunicado_oficial(titulo=titulo)
    assert resultado["sucesso"]
    campos = resultado["metadados"]["prompt_estruturado"]
    final = campos["prompt_completo_en"]
    assert final == ". ".join(v for k, v in campos.items() if k != "prompt_completo_en")
    assert cliente.text_to_image.call_args.args[0] == final
    assert titulo not in final
    assert "technical school courtyard" in campos["sujeito"]
    for proibicao in ("No words", "pseudo-writing", "signboards", "plaques", "banners",
                      "school name signs", "coats of arms"):
        assert proibicao in campos["restricoes"]
    assert resultado["metadados"]["composicao"]["titulo"] == titulo
    assert resultado["metadados"]["composicao"]["assunto"] == titulo
    assert "No medical coats, no stethoscopes, no clinical or hospital environment" in campos["restricoes"]
    conformidade = resultado["metadados"]["conformidade_seguranca"]
    assert conformidade["sem_pessoas_reais"] is None
    assert conformidade["sem_direitos_autorais_terceiros"] is None
    assert conformidade["ilustracao_sem_texto_placas_logos"] is None


def test_fonte_portugues_fallback_e_composicao(geracao, monkeypatch):
    from PIL import ImageFont, ImageDraw
    gerador, _, _, _ = geracao
    monkeypatch.setenv("IMAGE_FONT_PATH", "fonte-inexistente.ttf")
    fonte = gerador._fonte(24)
    assert isinstance(fonte, ImageFont.FreeTypeFont)
    for letra in "áéíóúãõâêôçÁÉÍÓÚÃÕÂÊÔÇ":
        assert bytes(fonte.getmask(letra)) != bytes(fonte.getmask("\ufffd"))
    original = ImageDraw.ImageDraw.text
    textos = []
    def conferir(draw, xy, text, *args, **kwargs):
        assert isinstance(kwargs["font"], ImageFont.FreeTypeFont)
        textos.append(text)
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", conferir)
    assert gerador.gerar_comunicado_oficial(titulo="MATRÍCULAS E EDUCAÇÃO")['sucesso']
    assert "MATRÍCULAS E EDUCAÇÃO" in textos
    assert "ASSUNTO: MATRÍCULAS E EDUCAÇÃO" in textos
    assert gerador.tarja_texto in textos


def test_sem_fonte_unicode_nao_finge_sucesso(geracao, monkeypatch):
    gerador, _, _, _ = geracao
    monkeypatch.setattr("src.image_generation.ImageFont.truetype", Mock(side_effect=OSError("ausente")))
    assert not gerador.gerar_comunicado_oficial()["sucesso"]


def test_brasao_ausente_nao_finge_conformidade(geracao):
    gerador, _, _, tmp = geracao
    gerador.logo_path = tmp / "ausente.png"
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"]
    assert not resultado["metadados"]["conformidade_seguranca"]["tarja_visivel_aplicada"]


@pytest.fixture
def geracao(tmp_path, monkeypatch):
    monkeypatch.delenv("IMAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("IMAGE_ENDPOINT_TOKEN", raising=False)
    monkeypatch.setenv("EXECUTION_MODE", "api")
    monkeypatch.setenv("HF_TOKEN", "hf-segredo-teste")
    monkeypatch.setenv("IMAGE_PROVIDER", "fal-ai")
    monkeypatch.setenv("IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    monkeypatch.setenv("IMAGE_SEED", "42")
    gerador = ImageGenerator()
    gerador.output_dir = tmp_path
    gerador.config.setdefault("paths", {})["resultados_logs"] = str(tmp_path / "logs")
    cliente = Mock()
    cliente.text_to_image.return_value = Image.new("RGB", (64, 64), "white")
    factory = Mock(return_value=cliente)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(InferenceClient=factory))
    return gerador, cliente, factory, tmp_path


def test_sdk_composicao_arte_metadados_auditoria(geracao):
    gerador, cliente, factory, _ = geracao
    resultado = gerador.gerar_comunicado_oficial()
    assert resultado["sucesso"]
    factory.assert_called_once_with(token="hf-segredo-teste", provider="fal-ai", timeout=60)
    cliente.text_to_image.assert_called_once_with(
        gerador.construir_prompt_estruturado()["prompt_completo_en"],
        model="black-forest-labs/FLUX.1-schnell", **gerador.image_params)
    meta = json.loads(resolver_caminho(resultado["caminho_metadados"]).read_text(encoding="utf-8"))
    assert meta["ia_gerada"] and meta["provedor_efetivo"] == "fal-ai"
    assert meta["dimensoes"] == "1080x1350"
    assert meta["dimensoes_arte"] == "64x64"
    assert meta["parametros_geracao"]["seed"] == 42
    assert meta["tempo_processamento_segundos"] >= 0
    assert meta["custo_usd"] is None
    assert meta["status_revisao"] == "pendente_revisao"
    assert meta["estado_imagem"] == "pendente_revisao"
    assert "Validado" not in meta["declaracao_proveniencia"]
    assert len(meta["sha256_arte_ia"]) == len(meta["sha256_imagem"]) == 64
    assert resolver_caminho(meta["arquivo_arte_ia"]).is_file()
    registro = json.loads((gerador.output_dir / "logs" / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8"))
    assert registro["provedor"] == "fal-ai"
    assert registro["detalhes_completos"]["identificador"] == meta["identificador"]
    assert registro["resultado_resumo"]["sucesso"]


@pytest.mark.parametrize("status,codigo", [(401, "autenticacao"), (403, "autenticacao"),
    (402, "cobranca_ou_creditos"), (429, "limite_requisicoes"), (503, "falha_geracao")])
def test_falha_real_sem_fallback_e_sem_credenciais(geracao, status, codigo):
    gerador, cliente, _, _ = geracao
    erro = RuntimeError("HF falhou hf-segredo-teste Bearer outra-credencial")
    erro.response = types.SimpleNamespace(status_code=status)
    cliente.text_to_image.side_effect = erro
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"] and resultado["codigo_erro"] == codigo
    assert not list(gerador.output_dir.glob("*.png"))
    assert resultado["metadados"]["provedor_efetivo"] is None
    assert not resultado["metadados"]["ia_gerada"]
    assert resultado["metadados"]["erro"]["status_http"] == status
    assert "hf-segredo-teste" not in json.dumps(resultado)
    assert "outra-credencial" not in json.dumps(resultado)
    registro = json.loads((gerador.output_dir / "logs" / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8"))
    assert not registro["resultado_resumo"]["sucesso"]
    assert registro["erros"] == [codigo]


def test_timeout(geracao):
    gerador, cliente, _, _ = geracao
    cliente.text_to_image.side_effect = TimeoutError("timeout real")
    assert gerador.gerar_comunicado_oficial()["codigo_erro"] == "timeout"


@pytest.mark.parametrize("caso", ["sem_token", "mock", "auto", "dependencia"])
def test_bloqueios_sem_chamada(geracao, monkeypatch, caso):
    gerador, cliente, _, _ = geracao
    if caso == "sem_token":
        monkeypatch.setenv("HF_TOKEN", "")
    elif caso == "mock":
        monkeypatch.setenv("EXECUTION_MODE", "mock")
    elif caso == "auto":
        gerador.image_provider = "auto"
    else:
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"]
    assert not list(gerador.output_dir.glob("*.png"))
    cliente.text_to_image.assert_not_called()


@pytest.mark.parametrize("retorno", [None, "imagem-invalida", Image.new("RGB", (0, 0))])
def test_resposta_invalida(geracao, retorno):
    gerador, cliente, _, _ = geracao
    cliente.text_to_image.return_value = retorno
    assert not gerador.gerar_comunicado_oficial()["sucesso"]


def test_preserva_arquivos_existentes(geracao):
    gerador, _, _, tmp = geracao
    arquivo = tmp / "comunicado_institucional_govmt.png"
    arquivo.write_bytes(b"conteudo anterior")
    resultado = gerador.gerar_comunicado_oficial()
    assert resultado["sucesso"]
    assert arquivo.read_bytes() == b"conteudo anterior"
    assert resolver_caminho(resultado["caminho_imagem"]) != arquivo


def test_configuracao_modelo_provedor(geracao, monkeypatch):
    gerador, cliente, factory, _ = geracao
    gerador.image_provider = "nscale"
    gerador.image_model = "modelo-configurado"
    gerador.image_params["seed"] = 7
    assert gerador.gerar_comunicado_oficial()["sucesso"]
    assert factory.call_args.kwargs["provider"] == "nscale"
    assert cliente.text_to_image.call_args.kwargs["model"] == "modelo-configurado"
    assert cliente.text_to_image.call_args.kwargs["seed"] == 7


def test_caminho_invalido_nao_chama_provedor(geracao):
    gerador, cliente, _, _ = geracao
    assert not gerador.gerar_comunicado_oficial(nome_arquivo="../fora.png")["sucesso"]
    cliente.text_to_image.assert_not_called()


def test_falha_composicao_registra_arte_real_sem_sucesso_falso(geracao, monkeypatch):
    gerador, cliente, _, _ = geracao
    monkeypatch.setattr(gerador, "montar_template_institucional", Mock(side_effect=ValueError("Falha na composição")))
    resultado = gerador.gerar_comunicado_oficial()
    assert not resultado["sucesso"]
    assert resultado["metadados"]["ia_gerada"]
    assert resultado["metadados"]["estado_imagem"] == "gerada"
    assert resultado["metadados"]["provedor_efetivo"] == "fal-ai"
    assert "caminho_imagem" not in resultado
    cliente.text_to_image.assert_called_once()


def test_servidor_hf_compativel_sem_enviar_token_hf(geracao, monkeypatch):
    gerador, cliente, factory, _ = geracao
    gerador.image_endpoint = "http://servidor-gpu:8080/generate"
    monkeypatch.setenv("HF_TOKEN", "")
    resultado = gerador.gerar_comunicado_oficial()
    assert resultado["sucesso"]
    factory.assert_called_once_with(token="", headers={"authorization": ""}, provider="hf-inference", timeout=60)
    assert cliente.text_to_image.call_args.kwargs["model"] == gerador.image_endpoint
    assert resultado["metadados"]["provedor_efetivo"] == "endpoint_hf_compativel"


@pytest.mark.parametrize("decisao,estado", [("APROVADO", "aprovada"), ("REJEITADO", "rejeitada")])
def test_revisao_humana_persistida_sem_alterar_pixels(geracao, decisao, estado):
    gerador, _, _, _ = geracao
    original = gerador.gerar_comunicado_oficial()
    hash_imagem = original["metadados"]["sha256_imagem"]
    resultado = gerador.revisar_imagem(original["id_execucao"], hash_imagem, decisao, "Conferi a peça", "Revisor teste")
    assert resultado["sucesso"]
    assert resultado["metadados"]["estado_imagem"] == estado
    assert resultado["metadados"]["revisao_humana"]["hash_imagem"] == hash_imagem
    assert resultado["metadados"]["id_execucao_geracao"] == original["id_execucao"]
    assert resultado["caminho_imagem"] == original["caminho_imagem"]
    assert resultado["caminho_metadados"] != original["caminho_metadados"]
    pendente = json.loads(resolver_caminho(original["caminho_metadados"]).read_text(encoding="utf-8"))
    assert pendente["estado_imagem"] == "pendente_revisao"
    aprovado = json.loads(resolver_caminho(resultado["caminho_metadados"]).read_text(encoding="utf-8"))
    assert aprovado["estado_imagem"] == estado
    log = json.loads((gerador.output_dir / "logs" / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8"))
    assert log["decisao_humana"]["status"] == decisao


@pytest.mark.parametrize("caso", ["hash", "pixels", "justificativa", "responsavel", "sem_registro"])
def test_aprovacao_invalida_bloqueada(geracao, caso):
    gerador, _, _, _ = geracao
    original = gerador.gerar_comunicado_oficial()
    identificador = original["id_execucao"]
    hash_imagem = original["metadados"]["sha256_imagem"]
    if caso == "hash":
        hash_imagem = "divergente"
    elif caso == "pixels":
        resolver_caminho(original["caminho_imagem"]).write_bytes(b"alterado")
    elif caso == "sem_registro":
        identificador = "EXEC_inexistente"
    resultado = gerador.revisar_imagem(identificador, hash_imagem, "APROVADO",
        "" if caso == "justificativa" else "Conferido", "" if caso == "responsavel" else "Revisor teste")
    assert not resultado["sucesso"]


def test_endpoint_sdk_instalado_sem_rede_sem_token_implicito(tmp_path, monkeypatch):
    import io
    from huggingface_hub import InferenceClient
    monkeypatch.setenv("IMAGE_PROVIDER", "hf-inference")
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("HTTP real proibido neste teste")))
    monkeypatch.setenv("EXECUTION_MODE", "api")
    monkeypatch.setenv("IMAGE_ENDPOINT", "http://servidor-gpu:8080/generate")
    monkeypatch.delenv("IMAGE_ENDPOINT_TOKEN", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_nao_enviar_ao_endpoint")
    recebido = []
    png = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(png, format="PNG")
    def transporte_simulado(self, request_parameters):
        recebido.append(request_parameters)
        return png.getvalue()
    monkeypatch.setattr(InferenceClient, "_inner_post", transporte_simulado)
    gerador = ImageGenerator()
    gerador.output_dir = tmp_path
    gerador.config["paths"]["resultados_logs"] = str(tmp_path / "logs")
    resultado = gerador.gerar_comunicado_oficial()
    assert resultado["sucesso"]
    assert len(recebido) == 1
    assert recebido[0].url == "http://servidor-gpu:8080/generate"
    assert not recebido[0].headers.get("authorization")
