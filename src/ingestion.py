"""
ingestion.py - Extração de Documentos, Metadados e Estratégias de Chunking (RF17/RF18)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Suporta leitura de TXT e PDF textual via PyMuPDF e oferece duas configurações de chunking
comparáveis (Config A: 400/80 e Config B: 800/150).
"""

import os
import hashlib
import re
from typing import List, Dict, Any, Optional
import pymupdf


class ChunkDocumento:
    def __init__(
        self,
        documento_id: str,
        versao: str,
        titulo: str,
        trecho_id: str,
        conteudo: str,
        pagina: Optional[int] = 1,
        secao: Optional[str] = None,
        hash_arquivo: str = "",
        configuracao: str = "A",
    ):
        self.documento_id = documento_id
        self.versao = versao
        self.titulo = titulo
        self.trecho_id = trecho_id
        self.conteudo = conteudo.strip()
        self.pagina = pagina
        self.secao = secao
        self.hash_arquivo = hash_arquivo
        self.configuracao = configuracao
        self.chunk_hash = hashlib.sha256(
            f"{documento_id}_{configuracao}_{trecho_id}_{self.conteudo}".encode("utf-8")
        ).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "documento_id": self.documento_id,
            "versao": self.versao,
            "titulo": self.titulo,
            "trecho_id": self.trecho_id,
            "conteudo": self.conteudo,
            "pagina": self.pagina,
            "secao": self.secao,
            "hash_arquivo": self.hash_arquivo,
            "configuracao": self.configuracao,
            "chunk_hash": self.chunk_hash,
        }


def extrair_metadados_cabecalho(texto: str) -> Dict[str, str]:
    """Extrai campos padrão de cabeçalho (IDENTIFICADOR, TITULO, VERSAO, DATA_PUBLICACAO)."""
    meta = {
        "documento_id": "DOC-DESCONHECIDO",
        "titulo": "Documento Institucional",
        "versao": "1.0",
        "data_publicacao": "não localizada",
    }
    cabecalho = texto.split("\n\n", 1)[0]
    chave_atual: Optional[str] = None
    for line in cabecalho.splitlines()[:14]:
        linha_limpa = line.strip()
        if not linha_limpa:
            continue
        m_campo = re.match(
            r"^(IDENTIFICADOR|ID|TITULO|TÍTULO|VERSAO|VERSÃO|DATA_PUBLICACAO|DATA|DOCUMENTO_PAI|TEMAS)\s*:\s*(.*)$",
            linha_limpa,
            re.I,
        )
        if m_campo:
            k = m_campo.group(1).upper()
            v = m_campo.group(2).strip()
            if k in ("IDENTIFICADOR", "ID"):
                meta["documento_id"] = v
                chave_atual = "documento_id"
            elif k in ("TITULO", "TÍTULO"):
                meta["titulo"] = v
                chave_atual = "titulo"
            elif k in ("VERSAO", "VERSÃO"):
                meta["versao"] = v
                chave_atual = "versao"
            elif k in ("DATA_PUBLICACAO", "DATA"):
                meta["data_publicacao"] = v
                chave_atual = "data_publicacao"
            else:
                chave_atual = None
        elif chave_atual == "titulo":
            meta["titulo"] = f"{meta['titulo']} {linha_limpa}".strip()
    return meta


def _normalizar_quebras_pdf(texto: str) -> str:
    """Une quebras de linha artificiais dentro de um mesmo parágrafo extraído de PDF."""
    linhas = texto.splitlines()
    saida: List[str] = []
    for linha in linhas:
        l_strip = linha.strip()
        if not l_strip:
            saida.append("")
            continue
        eh_cabecalho_ou_item = bool(
            re.match(
                r"^(IDENTIFICADOR|TITULO|VERSAO|DATA_PUBLICACAO|DOCUMENTO_PAI|TEMAS|Art\.|CAPÍTULO|SEÇÃO|Item|\d+\.|[IVX]+\s*-|[a-z]\)|-)",
                l_strip,
            )
        )
        if (
            saida
            and saida[-1]
            and not eh_cabecalho_ou_item
            and not saida[-1].endswith((".", ":", ";"))
            and not re.match(r"^(IDENTIFICADOR|VERSAO|DATA_PUBLICACAO|DOCUMENTO_PAI|TEMAS)\s*:", saida[-1])
        ):
            saida[-1] = f"{saida[-1]} {l_strip}"
        else:
            saida.append(l_strip)
    return "\n".join(saida)


def ler_arquivo(caminho_arquivo: str) -> List[Dict[str, Any]]:
    """Lê arquivo TXT ou PDF retornando lista de páginas com texto íntegro e metadados."""
    if not os.path.exists(caminho_arquivo):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")

    with open(caminho_arquivo, "rb") as f:
        conteudo_bytes = f.read()
    hash_arq = hashlib.sha256(conteudo_bytes).hexdigest()

    nome_base = os.path.basename(caminho_arquivo)
    paginas = []

    if caminho_arquivo.lower().endswith(".txt"):
        texto = conteudo_bytes.decode("utf-8", errors="replace")
        meta = extrair_metadados_cabecalho(texto)
        paginas.append({
            "pagina": 1,
            "texto": texto,
            "hash_arquivo": hash_arq,
            "nome_arquivo": nome_base,
            **meta,
        })

    elif caminho_arquivo.lower().endswith(".pdf"):
        doc = pymupdf.open(caminho_arquivo)
        textos_pags = [_normalizar_quebras_pdf(page.get_text()) for page in doc]
        texto_completo = "\n".join(textos_pags)
        meta = extrair_metadados_cabecalho(texto_completo)
        for i, t in enumerate(textos_pags):
            if t.strip():
                paginas.append({
                    "pagina": i + 1,
                    "texto": t,
                    "hash_arquivo": hash_arq,
                    "nome_arquivo": nome_base,
                    **meta,
                })
        doc.close()
    else:
        raise ValueError(f"Formato não suportado para ingestão de acervo: {caminho_arquivo}")

    return paginas


def identificar_secao(texto: str) -> Optional[str]:
    """Identifica títulos de seção, artigos ou itens no trecho."""
    match = re.search(r"(?:^|\n)(Art\.?\s*\d+º?|Item\s*\d+(?:\.\d+)*|CAPÍTULO\s+[IVX]+|\d+\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]+)", texto)
    if match:
        return match.group(0).strip()
    return None


def dividir_em_chunks(
    paginas: List[Dict[str, Any]],
    configuracao: str = "A",
) -> List[ChunkDocumento]:
    """
    Divide o texto do documento em chunks com metadados (RF17 / RF18).
    Configuração A: 400 caracteres com sobreposição de 80.
    Configuração B: 800 caracteres com sobreposição de 150.
    """
    if configuracao.upper() == "A":
        tamanho_chunk = 400
        sobreposicao = 80
        cfg_label = "A"
    else:
        tamanho_chunk = 800
        sobreposicao = 150
        cfg_label = "B"

    chunks_resultado: List[ChunkDocumento] = []

    for pag in paginas:
        texto = pag["texto"]
        doc_id = pag["documento_id"]
        versao = pag["versao"]
        titulo = pag["titulo"]
        num_pag = pag["pagina"]
        hash_arq = pag["hash_arquivo"]

        inicio = 0
        idx_trecho = 1
        tamanho_texto = len(texto)

        while inicio < tamanho_texto:
            fim = min(inicio + tamanho_chunk, tamanho_texto)
            trecho = texto[inicio:fim]

            if fim < tamanho_texto:
                ultimo_espaco = trecho.rfind(" ")
                if ultimo_espaco > tamanho_chunk // 2:
                    trecho = trecho[:ultimo_espaco]
                    fim = inicio + ultimo_espaco

            trecho_limpo = trecho.strip()
            if trecho_limpo:
                secao = identificar_secao(trecho_limpo)
                conteudo_ancorado = f"[{doc_id} - {titulo}]\n{trecho_limpo}"
                chunk_obj = ChunkDocumento(
                    documento_id=doc_id,
                    versao=versao,
                    titulo=titulo,
                    trecho_id=f"{doc_id}-p{num_pag}-c{idx_trecho:03d}",
                    conteudo=conteudo_ancorado,
                    pagina=num_pag,
                    secao=secao,
                    hash_arquivo=hash_arq,
                    configuracao=cfg_label,
                )
                chunks_resultado.append(chunk_obj)
                idx_trecho += 1

            if fim >= tamanho_texto:
                break
            inicio += (tamanho_chunk - sobreposicao)

    return chunks_resultado


def carregar_acervo_completo(diretorio: str = "dados/acervo", configuracao: str = "A") -> List[ChunkDocumento]:
    """Lê todos os documentos (.txt e .pdf) do diretório de acervo e retorna seus chunks."""
    if not os.path.exists(diretorio):
        return []
    arquivos = sorted([
        os.path.join(diretorio, f)
        for f in os.listdir(diretorio)
        if f.lower().endswith((".txt", ".pdf"))
    ])
    todos_chunks: List[ChunkDocumento] = []
    for arq in arquivos:
        pags = ler_arquivo(arq)
        todos_chunks.extend(dividir_em_chunks(pags, configuracao=configuracao))
    return todos_chunks
