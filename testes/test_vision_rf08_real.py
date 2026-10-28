import sys
"""Validação opt-in: RF08_REAL=1. OCR real, local; nenhum resultado simulado."""
import hashlib
import io
import json
import os
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from src import resolver_caminho
from src import vision
from src.audit import AuditLogger

pytestmark = pytest.mark.skipif(os.getenv("RF08_REAL") != "1", reason="OCR real somente por execução explícita")


@pytest.fixture(scope="module")
def cenario(tmp_path_factory):
    base = tmp_path_factory.mktemp("validacao_rf08")
    base.mkdir(parents=True, exist_ok=True)
    # Referência própria do documento sintético. Nunca preenche resultados do OCR.
    campos = {
        "codigo": "55555555", "nome": "Pessoa Alfa Teste", "data_nascimento": "12/12/2012",
        "cpf": "000.000.000-00", "rg": "0000000-0", "orgao_expedidor": "Orgao Ficticio",
        "naturalidade": "Cidade Teste", "uf": "MT", "nome_mae": "Pessoa Beta Teste",
        "nome_pai": "Pessoa Gama Teste", "curso": "Curso de Teste", "ch": "800 horas",
        "eixo_tecnologico": "Tecnologia", "turma": "ALFA", "municipio": "Cidade Teste",
        "turno": "Noturno", "inicio_curso": "12/12/2032", "termino_curso": "12/12/2033",
        "tel_celular": "99999999999", "tel_residencial": "8888888888",
        "email": "teste@example.com", "data_matricula": "12/12/2031",
        "assinatura_aluno": "Registro ficticio",
    }
    imagem = Image.new("RGB", (2480, 3508), "white")
    draw = ImageDraw.Draw(imagem)
    # Descoberta dinâmica de fontes TrueType multiplataforma (Windows / Linux / macOS)
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    candidatos = [
        os.getenv("IMAGE_FONT_PATH"),
        str(Path(windir) / "Fonts" / "arial.ttf") if sys.platform == "win32" else None,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "DejaVuSans.ttf",
        "arial.ttf",
    ]
    font = None
    for cand in candidatos:
        if cand:
            try:
                font = ImageFont.truetype(cand, 44)
                break
            except (OSError, ValueError):
                continue
    if font is None:
        font = ImageFont.load_default()
    draw.text((100, 70), "TESTE SINTETICO - SEM VALIDADE", font=font, fill="black")
    labels = {"tel_celular": "TELEFONE CELULAR", "ch": "CARGA HORARIA"}
    for i, (campo, valor) in enumerate(campos.items()):
        label = labels.get(campo, vision.ROTULOS[campo][0].upper())
        draw.text((100, 220 + 120 * i), f"{label}: {valor}", font=font, fill="black")
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG", dpi=(300, 300))
    pdf = base / "formulario_sintetico_rasterizado.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buffer.getvalue())
        doc.save(str(pdf))
    referencia = base / "gabarito_sintetico.json"
    referencia.write_text(json.dumps({"campos_esperados": campos}, ensure_ascii=False, indent=2), encoding="utf-8")
    protegidos = [p for p in [resolver_caminho("dados/originais/entrada_pdf-imagem.pdf"),
                               resolver_caminho("dados/gabaritos/gabarito_visao.json")] if p.is_file()]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protegidos}
    yield base, pdf, referencia
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items())


def executar_e_conferir(base, pdf, nome):
    proc = vision.VisionProcessor()
    proc.config.setdefault("paths", {})["dados_processados"] = str(base)
    logger = AuditLogger(str(base / "logs"))
    resultado = proc.processar_com_auditoria(logger, str(pdf))
    assert resultado["sucesso"], resultado.get("codigo_erro")
    salvo = json.loads(resolver_caminho(resultado["arquivo_extracao"]).read_text(encoding="utf-8"))
    for chave in ["texto_bruto", "texto_corrigido", "campos_extraidos", "comparacao_gabarito", "versoes_ocr"]:
        # JSON converte tuplas das coordenadas em listas, sem perda de informação.
        assert salvo[chave] == json.loads(json.dumps(resultado[chave]))
    log = json.loads((logger.log_dir / f"{resultado['id_execucao']}.json").read_text(encoding="utf-8"))
    assert log["detalhes_completos"]["arquivo_extracao"] == resultado["arquivo_extracao"]
    assert log["duracao_segundos"] == resultado["tempo_processamento_segundos"]
    assert log["provedor"] == resultado["provedor"]
    assert log["decisao_humana"]["status"] == "pendente_revisao"
    assert log["resultado_resumo"]["sucesso"]
    trilha = [json.loads(l) for l in logger.trail_file.read_text(encoding="utf-8").splitlines()]
    assert any(l["id_execucao"] == resultado["id_execucao"] for l in trilha)
    detalhes = resultado["comparacao_gabarito"]["detalhes"]
    resumo = {
        "cenario": nome, "acertos": resultado["comparacao_gabarito"]["campos_conferidos"],
        "total": resultado["comparacao_gabarito"]["total_campos"],
        "reconhecidos": [c for c, v in detalhes.items() if v["conferido_com_sucesso"]],
        "nao_reconhecidos_ou_divergentes": [c for c, v in detalhes.items() if not v["conferido_com_sucesso"]],
        "tempo_segundos": round(resultado["tempo_processamento_segundos"], 2),
        "revisao_humana_obrigatoria": resultado["exige_confirmacao_humana"],
        "arquivo_extracao": resultado["arquivo_extracao"], "id_execucao": resultado["id_execucao"],
        "erros": {e: v.get("erros", []) for e, v in resultado["versoes_ocr"].items()},
    }
    (base / f"resumo_{nome}.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=True))
    return resultado


def test_sintetico_ocr_real(cenario, monkeypatch):
    base, pdf, referencia = cenario
    with pymupdf.open(str(pdf)) as doc:
        assert all(not page.get_text().strip() and page.get_images() for page in doc)
    original = vision.resolver_caminho
    # Isola somente a referência de avaliação; OCR e extração permanecem reais.
    monkeypatch.setattr(vision, "resolver_caminho", lambda caminho:
        referencia if str(caminho) == "dados/gabaritos/gabarito_visao.json" else original(caminho))
    resultado = executar_e_conferir(base, pdf, "sintetico")
    comparacao = resultado["comparacao_gabarito"]
    assert comparacao["total_campos"] == 23
    # Confere dados críticos e classificação completa; não presume OCR perfeito.
    for campo in ["codigo", "nome", "data_nascimento", "cpf", "rg", "curso", "data_matricula"]:
        assert comparacao["detalhes"][campo]["conferido_com_sucesso"], campo
    assert comparacao["campos_conferidos"] == sum(
        v["conferido_com_sucesso"] for v in comparacao["detalhes"].values())
    assert resultado["perfil_regional"] == "não aplicado"


def test_oficial_baixa_qualidade_ocr_real(cenario):
    base, _, _ = cenario
    resultado = executar_e_conferir(base, resolver_caminho("dados/originais/entrada_pdf-imagem.pdf"), "oficial")
    assert resultado["exige_confirmacao_humana"]
    assert resultado["trechos_incertos_ou_ilegiveis"]
    assert resultado["perfil_regional"] == "oficial_sha256"
