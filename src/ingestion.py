"""
ingestion.py - Extração de Documentos, Metadados e Estratégias de Chunking (RF17/RF18)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Suporta leitura de TXT e PDF textual via PyMuPDF e oferece duas configurações de chunking.
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
        configuracao: str = "A"
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
        self.chunk_hash = hashlib.sha256(f"{documento_id}_{trecho_id}_{self.conteudo}".encode("utf-8")).hexdigest()[:16]

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
            "chunk_hash": self.chunk_hash
        }


def extrair_metadados_cabecalho(texto: str) -> Dict[str, str]:
    """Extrai campos padrão de cabeçalho (IDENTIFICADOR, TITULO, VERSAO, DATA_PUBLICACAO)."""
    meta = {
        "documento_id": "DOC-DESCONHECIDO",
        "titulo": "Documento Institucional",
        "versao": "1.0",
        "data_publicacao": "não localizada"
    }
    for line in texto.splitlines()[:10]:
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().upper()
            v = v.strip()
            if k in ("IDENTIFICADOR", "ID"):
                meta["documento_id"] = v
            elif k in ("TITULO", "TÍTULO"):
                meta["titulo"] = v
            elif k in ("VERSAO", "VERSÃO"):
                meta["versao"] = v
            elif k in ("DATA_PUBLICACAO", "DATA"):
                meta["data_publicacao"] = v
    return meta


def ler_arquivo(caminho_arquivo: str) -> List[Dict[str, Any]]:
    """Lê arquivo TXT ou PDF retornando lista de páginas com texto e metadados."""
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
            **meta
        })

    elif caminho_arquivo.lower().endswith(".pdf"):
        doc = pymupdf.open(caminho_arquivo)
        texto_completo = "\n".join([page.get_text() for page in doc])
        meta = extrair_metadados_cabecalho(texto_completo)
        for i, page in enumerate(doc):
            t = page.get_text()
            if t.strip():
                paginas.append({
                    "pagina": i + 1,
                    "texto": t,
                    "hash_arquivo": hash_arq,
                    "nome_arquivo": nome_base,
                    **meta
                })
        doc.close()
    else:
        raise ValueError(f"Formato não suportado para ingestão de acervo: {caminho_arquivo}")

    return paginas


def identificar_secao(texto: str) -> Optional[str]:
    """Identifica títulos de seção, artigos ou itens no trecho."""
    match = re.search(r"(?:^|\n)(Art\.?\s*\d+º?|Item\s*\d+(\.\d+)*|\d+\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]+)", texto)
    if match:
        return match.group(0).strip()
    return None


def dividir_em_chunks(
    paginas: List[Dict[str, Any]],
    configuracao: str = "A"
) -> List[ChunkDocumento]:
    """
    Divide o texto do documento em chunks com metadados.
    Configuração A: Chunks de tamanho moderado (400 caracteres com sobreposição de 80).
    Configuração B: Chunks maiores orientados a parágrafos/seções (800 caracteres com sobreposição de 150).
    """
    if configuracao == "A":
        tamanho_chunk = 400
        sobreposicao = 80
    else:  # Configuração B
        tamanho_chunk = 800
        sobreposicao = 150

    chunks_resultado = []
    
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

            # Ajusta para não quebrar no meio de palavras quando possível
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
                    configuracao=configuracao
                )
                chunks_resultado.append(chunk_obj)
                idx_trecho += 1

            if fim >= tamanho_texto:
                break
            inicio += (tamanho_chunk - sobreposicao)

    return chunks_resultado
