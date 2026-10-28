"""RF08: OCR simulado; persistência/auditoria reais em diretório temporário."""
import json
from unittest.mock import MagicMock, Mock

import pytest

from src import vision
from src.audit import AuditLogger


def test_descoberta_tesseract_nao_depende_path(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "TESSERACT_DIR", tmp_path)
    (tmp_path / "tesseract.exe").write_bytes(b"executavel ficticio")
    (tmp_path / "tessdata").mkdir()
    monkeypatch.setattr(vision.shutil, "which", lambda _: None)
    assert vision.VisionProcessor.obter_executavel_tesseract() == tmp_path / "tesseract.exe"
    assert vision.VisionProcessor.obter_tessdata_dir() == tmp_path / "tessdata"


@pytest.fixture
def ocr(tmp_path, monkeypatch):
    tess = tmp_path / "tesseract"
    (tess / "tessdata").mkdir(parents=True)
    (tess / "tesseract.exe").touch()
    (tess / "tessdata" / "por.traineddata").touch()
    monkeypatch.setattr(vision, "TESSERACT_DIR", tess)
    monkeypatch.setenv("VISION_PROVIDER", "local")
    path = tmp_path / "documento.pdf"
    path.write_bytes(b"documento simulado")
    page = Mock()
    page.get_text.return_value = "NOME: Ana Ficticia\nCPF: 000.000.000-00\nCURSO: Teste"
    doc = MagicMock()
    doc.needs_pass = False
    doc.__len__.return_value = 1
    doc.__iter__.side_effect = lambda: iter([page])
    doc.__enter__.return_value = doc
    abrir = Mock(return_value=doc)
    monkeypatch.setattr(vision.pymupdf, "open", abrir)
    proc = vision.VisionProcessor()
    monkeypatch.setattr(proc, "_ocr_alternativo", Mock(side_effect=lambda *_: page.get_text.return_value))
    proc.config = {"paths": {"dados_processados": str(tmp_path / "processados")}}
    return proc, path, page, doc, abrir


def test_ocr_real_contrato_multiplas_paginas(ocr):
    proc, path, page, doc, _ = ocr
    segunda = Mock()
    segunda.get_text.return_value = "PROTOCOLO: 2020-001"
    doc.__len__.return_value = 2
    doc.__iter__.side_effect = lambda: iter([page, segunda])
    resultado = proc.processar_documento(str(path))
    assert resultado["sucesso"]
    assert resultado["paginas_processadas"] == 2
    assert resultado["texto_bruto"] == page.get_text.return_value + "\n\f\n" + segunda.get_text.return_value
    assert resultado["campos_extraidos"]["nome"] == "Ana Ficticia"
    assert resultado["exige_confirmacao_humana"]
    assert resultado["trechos_incertos_ou_ilegiveis"]
    assert resultado["tempo_processamento_segundos"] >= 0
    page.get_textpage_ocr.assert_called_once_with(language="por", dpi=300, full=True,
        tessdata=str(vision.TESSERACT_DIR / "tessdata"))
    segunda.get_textpage_ocr.assert_called_once()
    doc.__exit__.assert_called_once()


@pytest.mark.parametrize("caso,codigo", [("invalido", "pdf_invalido"), ("vazio", "ocr_vazio"),
    ("falha", "falha_ocr"), ("protegido", "pdf_invalido"), ("sem_paginas", "pdf_invalido")])
def test_falhas_sem_sucesso_falso(ocr, caso, codigo):
    proc, path, page, doc, abrir = ocr
    if caso == "invalido":
        abrir.side_effect = vision.pymupdf.FileDataError("inválido")
    elif caso == "vazio":
        page.get_text.return_value = " \n"
    elif caso == "falha":
        page.get_textpage_ocr.side_effect = RuntimeError("detalhe interno")
        proc._ocr_alternativo.side_effect = RuntimeError("detalhe interno")
    elif caso == "protegido":
        doc.needs_pass = True
    else:
        doc.__len__.return_value = 0
    resultado = proc.processar_documento(str(path))
    assert not resultado["sucesso"]
    assert resultado["codigo_erro"] == codigo
    assert "detalhe interno" not in json.dumps(resultado)


@pytest.mark.parametrize("caso", ["ausente", "extensao", "vazio", "sem_idioma"])
def test_validacao_previa(ocr, caso):
    proc, path, page, _, abrir = ocr
    if caso == "ausente":
        path.unlink()
    elif caso == "extensao":
        path = path.rename(path.with_suffix(".txt"))
    elif caso == "vazio":
        path.write_bytes(b"")
    else:
        (vision.TESSERACT_DIR / "tessdata" / "por.traineddata").unlink()
    assert not proc.processar_documento(str(path))["sucesso"]
    abrir.assert_not_called()
    page.get_textpage_ocr.assert_not_called()


def test_comparacao_por_campo_sem_acertos_ausentes(ocr, tmp_path, monkeypatch):
    proc, _, _, _, _ = ocr
    gabarito = tmp_path / "gabarito.json"
    gabarito.write_text(json.dumps({"campos_esperados": {
        "nome": "Ána Fictícia", "cpf": "000.000.000-00", "uf": "não localizado", "codigo": "1234"
    }}), encoding="utf-8")
    monkeypatch.setattr(vision, "resolver_caminho", lambda _: gabarito)
    assert proc.comparar_com_gabarito("")["campos_conferidos"] == 0
    resultado = proc.comparar_com_gabarito("NOME: Ana Ficticia\nCPF: 00000000000\nCODIGO: 12345")
    assert resultado["campos_conferidos"] == 2
    assert not resultado["detalhes"]["codigo"]["conferido_com_sucesso"]
    assert not resultado["detalhes"]["uf"]["conferido_com_sucesso"]


def test_campos_repetidos_e_vazios_exigem_revisao(ocr):
    proc, _, _, _, _ = ocr
    campos = proc._extrair_campos("NOME: Ana\nNOME: Outra\nCPF: [ ]\nCURSO: Teste")
    assert campos["nome"] == campos["cpf"] == "não localizado"
    assert campos["curso"] == "Teste"


def test_persistencia_e_auditoria(ocr, tmp_path):
    proc, path, _, _, _ = ocr
    logger = AuditLogger(str(tmp_path / "logs"))
    resultado = proc.processar_com_auditoria(logger, str(path))
    arquivo = vision.resolver_caminho(resultado["arquivo_extracao"])
    salvo = json.loads(arquivo.read_text(encoding="utf-8"))
    assert salvo["texto_bruto"] == resultado["texto_bruto"]
    assert salvo["comparacao_gabarito"] == resultado["comparacao_gabarito"]
    registro = json.loads((logger.log_dir / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8"))
    assert registro["provedor"] == resultado["provedor"]
    assert registro["duracao_segundos"] == resultado["tempo_processamento_segundos"]
    assert registro["decisao_humana"]["status"] == "pendente_revisao"
    assert registro["resultado_resumo"]["sucesso"]
    assert registro["detalhes_completos"]["arquivo_extracao"] == resultado["arquivo_extracao"]


def test_falha_auditada(ocr, tmp_path):
    proc, path, page, _, _ = ocr
    page.get_text.return_value = ""
    logger = AuditLogger(str(tmp_path / "logs"))
    resultado = proc.processar_com_auditoria(logger, str(path))
    assert not resultado["sucesso"]
    registro = json.loads(logger.trail_file.read_text(encoding="utf-8"))
    assert not registro["resultado_resumo"]["sucesso"]
    assert registro["erros"] == ["ocr_vazio"]


def test_falha_persistencia(ocr, tmp_path):
    proc, path, _, _, _ = ocr
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("teste", encoding="utf-8")
    proc.config["paths"]["dados_processados"] = str(bloqueio)
    resultado = proc.processar_com_auditoria(AuditLogger(str(tmp_path / "logs")), str(path))
    assert not resultado["sucesso"]
    assert resultado["codigo_erro"] == "falha_persistencia"


def test_preserva_versoes_sem_escolher_maior_ou_gabarito(ocr):
    proc, path, page, _, _ = ocr
    page.get_text.return_value = "NOME:\nAna Ficticia"
    proc._ocr_alternativo.side_effect = lambda *_: "NOME:\nOutra Pessoa\nCURSO:\nTeste" + "\nruido" * 20
    resultado = proc.processar_documento(str(path))
    assert resultado["campos_extraidos"]["nome"] == "Ana Ficticia"
    assert resultado["versoes_ocr"]["psm11"]["campos_extraidos"]["nome"] == "Outra Pessoa"
    assert "nome" in resultado["divergencias_entre_estrategias"]
    assert resultado["estrategias_por_pagina"] == ["pymupdf"]
    assert len(resultado["sha256_original"]) == 64


def test_fallback_quando_primeira_falha(ocr):
    proc, path, page, _, _ = ocr
    page.get_textpage_ocr.side_effect = RuntimeError()
    resultado = proc.processar_documento(str(path))
    assert resultado["sucesso"]
    assert resultado["estrategias_por_pagina"] == ["psm11"]
    assert resultado["versoes_ocr"]["pymupdf"]["erros"] == [{"pagina": 1, "codigo": "falha_ocr"}]


def test_segunda_falha_preserva_primeira(ocr):
    proc, path, _, _, _ = ocr
    proc._ocr_alternativo.side_effect = vision.subprocess.TimeoutExpired("tesseract", 90)
    resultado = proc.processar_documento(str(path))
    assert resultado["sucesso"]
    assert resultado["versoes_ocr"]["psm11"]["erros"] == [{"pagina": 1, "codigo": "timeout"}]


def test_rotulos_valores_multilinha_e_nao_invencao(ocr):
    proc, _, _, _, _ = ocr
    campos = proc._extrair_campos("NOME:\nAna\nFicticia\nCPF\n000.000.000-00\nCURSO:\nTecnico\nem Teste\nUF:")
    assert campos["nome"] == "Ana Ficticia"
    assert campos["cpf"] == "000.000.000-00"
    assert campos["curso"] == "Tecnico em Teste"
    assert campos["uf"] == "não localizado"


def test_tesseract_psm11_preprocessado_sem_path(ocr, monkeypatch):
    from PIL import Image
    import io
    proc, _, page, _, _ = ocr
    png = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(png, format="PNG")
    page.get_pixmap.return_value.tobytes.return_value = png.getvalue()
    run = Mock(return_value=Mock(returncode=0, stdout=b"texto"))
    monkeypatch.setattr(vision.subprocess, "run", run)
    texto = vision.VisionProcessor._ocr_alternativo(proc, page, vision.TESSERACT_DIR / "tessdata")
    assert texto == "texto"
    args, kwargs = run.call_args
    assert args[0][0] == str(vision.TESSERACT_DIR / "tesseract.exe")
    assert args[0][-2:] == ["--psm", "11"]
    with Image.open(io.BytesIO(kwargs["input"])) as imagem:
        assert imagem.mode == "L"
    assert kwargs["timeout"] == 90


def test_recortes_posicionais_psm6_psm7(ocr, monkeypatch):
    from PIL import Image
    import io
    proc, _, page, _, _ = ocr
    page.rect = vision.pymupdf.Rect(0, 0, 595, 842)
    png = io.BytesIO()
    Image.new("RGB", (100, 30), "white").save(png, format="PNG")
    page.get_pixmap.return_value.tobytes.return_value = png.getvalue()
    run = Mock(side_effect=lambda image, tessdata, psm, dpi: f"resultado-{psm}")
    monkeypatch.setattr(proc, "_executar_tesseract", run)
    versoes = proc._ocr_regioes(page, vision.TESSERACT_DIR / "tessdata")
    assert run.call_count == 2 * len(vision.REGIOES_OFICIAIS)
    for psm in (6, 7):
        regiao = versoes[f"regioes_psm{psm}"]["regioes"]["nome"]
        assert regiao["texto_bruto"] == f"resultado-{psm}"
        assert regiao["bbox_pontos"] == vision.REGIOES_OFICIAIS["nome"]
        assert regiao["dpi"] == 400
        assert len(regiao["sha256_recorte"]) == 64


def test_perfil_nao_aplicado_documento_desconhecido(ocr, monkeypatch):
    proc, path, _, _, _ = ocr
    executar = Mock()
    monkeypatch.setattr(proc, "_ocr_regioes", executar)
    assert proc.processar_documento(str(path))["perfil_regional"] == "não aplicado"
    executar.assert_not_called()


def test_consenso_regional_independe_gabarito(ocr, monkeypatch):
    proc, path, _, _, _ = ocr
    monkeypatch.setattr(vision, "FORMULARIO_SHA256", vision.hashlib.sha256(path.read_bytes()).hexdigest())
    campos6 = {c: vision.AUSENTE for c in vision.REGIOES_OFICIAIS}
    campos7 = campos6.copy()
    campos6.update(nome="Ana Ficticia", codigo="123")
    campos7.update(nome="Ana Ficticia", codigo="456")
    monkeypatch.setattr(proc, "_ocr_regioes", lambda *_: {
        "regioes_psm6": {"campos_extraidos": campos6, "erros": []},
        "regioes_psm7": {"campos_extraidos": campos7, "erros": []}})
    resultado = proc.processar_documento(str(path))
    assert resultado["campos_extraidos"]["nome"] == "Ana Ficticia"
    assert resultado["campos_extraidos"]["codigo"] == vision.AUSENTE
    assert "codigo" in resultado["divergencias_entre_estrategias"]
    assert resultado["comparacao_gabarito"]["campos_conferidos"] == 0


def test_geometria_incompativel(ocr):
    proc, _, page, _, _ = ocr
    page.rect = vision.pymupdf.Rect(0, 0, 600, 900)
    with pytest.raises(ValueError):
        proc._ocr_regioes(page, vision.TESSERACT_DIR / "tessdata")


def test_falha_recortes_nao_apaga_ocr_original(ocr, monkeypatch):
    proc, path, _, _, _ = ocr
    monkeypatch.setattr(vision, "FORMULARIO_SHA256", vision.hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(proc, "_ocr_regioes", Mock(side_effect=RuntimeError()))
    resultado = proc.processar_documento(str(path))
    assert resultado["sucesso"]
    assert resultado["erros_regioes"]
    assert resultado["texto_bruto"]


def test_obter_provedor_visao_prioridades(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert vision.VisionProcessor._obter_provedor_visao() == "local"

    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-teste")
    assert vision.VisionProcessor._obter_provedor_visao() == "openrouter"

    monkeypatch.setenv("VISION_PROVIDER", "local")
    assert vision.VisionProcessor._obter_provedor_visao() == "local"


def test_ocr_openrouter_vlm_sucesso(tmp_path, monkeypatch):
    pdf = tmp_path / "documento.pdf"
    pdf.write_bytes(b"conteudo ficticio")
    page = Mock()
    page.get_pixmap.return_value.tobytes.return_value = b"png-bytes"
    doc = MagicMock()
    doc.needs_pass = False
    doc.__len__.return_value = 1
    doc.__iter__.side_effect = lambda: iter([page])
    doc.__enter__.return_value = doc
    monkeypatch.setattr(vision.pymupdf, "open", Mock(return_value=doc))

    monkeypatch.setenv("VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-mock-key")
    monkeypatch.setenv("EXECUTION_MODE", "auto")

    resposta_mock = Mock()
    resposta_mock.status_code = 200
    resposta_mock.json.return_value = {
        "choices": [{
            "message": {
                "content": "CODIGO: 2026-000142\nNOME: Marcos Vinicius de Almeida Santos\nCPF: 123.456.789-00\nCURSO: Tecnico em Enfermagem\nASSINATURA DO ALUNO: Consta assinatura do aluno"
            }
        }]
    }

    import requests
    monkeypatch.setattr(requests, "post", Mock(return_value=resposta_mock))

    proc = vision.VisionProcessor()
    resultado = proc.processar_documento(str(pdf))
    assert resultado["sucesso"]
    assert "OpenRouter" in resultado["provedor"]
    assert resultado["campos_extraidos"]["codigo"] == "2026-000142"
    assert resultado["campos_extraidos"]["nome"] == "Marcos Vinicius de Almeida Santos"
    assert resultado["campos_extraidos"]["assinatura_aluno"] == "Consta assinatura do aluno"
    assert resultado["comparacao_gabarito"]["campos_conferidos"] >= 4


def test_ocr_openrouter_fallback_para_tesseract(ocr, monkeypatch):
    proc, path, page, doc, _ = ocr
    monkeypatch.setenv("VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-chave-invalida")
    monkeypatch.setenv("EXECUTION_MODE", "auto")

    import requests
    monkeypatch.setattr(requests, "post", Mock(side_effect=RuntimeError("Simulando falha de rede OpenRouter")))

    resultado = proc.processar_documento(str(path))
    assert resultado["sucesso"]
    assert resultado["provedor"] == "Tesseract local / PyMuPDF"
    assert "aviso_fallback" in resultado
    assert "OpenRouter VLM indisponível" in resultado["aviso_fallback"]

