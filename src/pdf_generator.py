"""
Modulo de Geracao de Documentos Oficiais em PDF (RF09)
Produz a minuta de resposta formal em documento PDF timbrado do Governo do Estado de Mato Grosso.
"""

from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Union
import pymupdf

from src import BASE_DIR, resolver_caminho, caminho_relativo


def normalizar_caracteres_pdf(texto: str) -> str:
    """Adapta pontuação à fonte PDF; não corrige nomes, fatos ou instituições."""
    trocas = {"—": " - ", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "•": "-", "\u00a0": " "}
    for origem, destino in trocas.items():
        texto = texto.replace(origem, destino)
    return texto


def _inserir_corpo(doc, pagina, texto, retangulo):
    """Paginação sem perda silenciosa: probes não são incorporados ao PDF."""
    restante = texto
    while restante:
        shape = pagina.new_shape()
        if shape.insert_textbox(retangulo, restante, fontsize=9.5, fontname="helv") >= 0:
            shape.commit()
            return
        baixo, alto, cabe = 1, len(restante), 0
        while baixo <= alto:
            meio = (baixo + alto) // 2
            probe = pagina.new_shape()
            if probe.insert_textbox(retangulo, restante[:meio], fontsize=9.5, fontname="helv") >= 0:
                cabe, baixo = meio, meio + 1
            else:
                alto = meio - 1
        if not cabe:
            raise ValueError("Não foi possível diagramar a minuta sem perder conteúdo.")
        corte = restante.rfind(" ", 0, cabe)
        corte = corte if corte > 0 else cabe
        shape = pagina.new_shape()
        shape.insert_textbox(retangulo, restante[:corte], fontsize=9.5, fontname="helv")
        shape.commit()
        restante = restante[corte:].lstrip()
        pagina = doc.new_page(width=595, height=842)
        pagina.insert_text(
            (45, 45),
            "CONTINUACAO - Documento gerado por IA com revisao humana",
            fontsize=8,
            fontname="helv",
            color=(100/255, 116/255, 139/255),
        )
        retangulo = pymupdf.Rect(45, 65, 550, 780)


def gerar_minuta_pdf(
    dados_extracao: Dict[str, Any],
    texto_minuta: str,
    caminho_saida_pdf: Union[str, Path],
    brasao_path: Optional[Union[str, Path]] = None,
    identificador_execucao: Optional[str] = None,
    fontes_origem: Optional[list] = None,
) -> str:
    """
    Gera um documento PDF oficial em formato A4 timbrado com brasao,
    identificacao do orgao, corpo da minuta e campo para assinatura formal.
    Todos os caminhos sao resolvidos dinamicamente de forma relativa a raiz do projeto.
    """
    saida_path = resolver_caminho(caminho_saida_pdf)
    saida_path.parent.mkdir(parents=True, exist_ok=True)

    caminho_brasao = resolver_caminho(brasao_path or "dados/originais/brasao.png")

    # Cria documento A4 (595.3 x 841.9 pontos)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    # 1. Faixa Tricolor Superior Oficial (Azul, Verde, Amarelo)
    page.draw_rect(pymupdf.Rect(0, 0, 198, 6), color=None, fill=(0/255, 74/255, 143/255))
    page.draw_rect(pymupdf.Rect(198, 0, 396, 6), color=None, fill=(0/255, 139/255, 71/255))
    page.draw_rect(pymupdf.Rect(396, 0, 595, 6), color=None, fill=(247/255, 181/255, 0/255))

    # 2. Insercao do Brasao de Mato Grosso
    if caminho_brasao.exists():
        try:
            page.insert_image(pymupdf.Rect(45, 30, 95, 80), filename=str(caminho_brasao))
        except Exception:
            pass

    # 3. Cabecalho Textual Institucional
    page.insert_text(
        (108, 45),
        "GOVERNO DO ESTADO DE MATO GROSSO",
        fontsize=11,
        fontname="helv",
        color=(0/255, 74/255, 143/255),
    )
    page.insert_text(
        (108, 60),
        "SECRETARIA DE ESTADO DE CIENCIA, TECNOLOGIA E INOVACAO - SECITECI/MT",
        fontsize=9,
        fontname="helv",
        color=(30/255, 41/255, 59/255),
    )
    page.insert_text(
        (108, 73),
        "ESCOLA TECNICA ESTADUAL DE CUIABA - UNIDADE INTEGRADA",
        fontsize=8,
        fontname="helv",
        color=(100/255, 116/255, 139/255),
    )

    # Linha separadora institucional
    page.draw_line(pymupdf.Point(45, 92), pymupdf.Point(550, 92), color=(200/255, 205/255, 215/255), width=1)

    # 4. Dados de Identificacao do Ato e Protocolo
    protocolo = dados_extracao.get("protocolo") or "não localizado"
    data_registro = dados_extracao.get("data")
    if data_registro and str(data_registro).strip().lower() != "não localizado":
        data_texto = f"Cuiaba-MT, {data_registro}"
        pos_x_data = 420
    else:
        data_texto = "Cuiaba-MT"
        pos_x_data = 485

    page.insert_text(
        (45, 115),
        f"COMUNICADO OFICIAL DE ATENDIMENTO Nº {protocolo}/SECITECI/ETEC",
        fontsize=10,
        fontname="helv",
        color=(0/255, 74/255, 143/255),
    )
    page.insert_text(
        (pos_x_data, 115),
        data_texto,
        fontsize=9,
        fontname="helv",
        color=(70/255, 80/255, 95/255),
    )

    # Aviso discreto de IA com revisão humana
    page.insert_text(
        (45, 132),
        "Documento gerado por Inteligencia Artificial com revisao humana",
        fontsize=7.5,
        fontname="helv",
        color=(120/255, 130/255, 145/255),
    )

    # 5. Corpo da Minuta
    texto_formatado = normalizar_caracteres_pdf(texto_minuta.replace("\\n", "\n").strip())
    rect_corpo = pymupdf.Rect(45, 148, 550, 715)
    _inserir_corpo(doc, page, texto_formatado, rect_corpo)
    page = doc[0]

    # Fontes de origem apenas se existirem dados validos
    fontes_validas = [f for f in (fontes_origem or []) if f and str(f).strip().lower() != "não localizado"]
    if fontes_validas:
        page.insert_textbox(
            pymupdf.Rect(45, 720, 550, 745),
            "Fontes: " + "; ".join(fontes_validas),
            fontsize=7,
            fontname="helv",
            color=(120/255, 130/255, 145/255),
        )

    # 6. Espaco para Assinatura do Servidor Responsavel
    page.draw_line(pymupdf.Point(170, 765), pymupdf.Point(425, 765), color=(150/255, 150/255, 150/255), width=1)
    page.insert_textbox(
        pymupdf.Rect(45, 770, 550, 786),
        "Servidor(a) Publico(a) Responsavel",
        fontsize=8.5,
        fontname="helv",
        color=(30/255, 41/255, 59/255),
        align=pymupdf.TEXT_ALIGN_CENTER,
    )
    page.insert_textbox(
        pymupdf.Rect(45, 785, 550, 801),
        "Secretaria de Estado de Ciencia, Tecnologia e Inovacao - SECITECI/MT",
        fontsize=7.5,
        fontname="helv",
        color=(100/255, 116/255, 139/255),
        align=pymupdf.TEXT_ALIGN_CENTER,
    )

    doc.save(str(saida_path))
    doc.close()
    return caminho_relativo(saida_path)

