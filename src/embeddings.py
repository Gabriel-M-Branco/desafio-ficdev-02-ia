"""
embeddings.py - Base Vetorial Persistente, Similaridade e Exclusão (RF17/RF18/RF21)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Implementa índice vetorial híbrido persistente em disco com metadados, versão do índice,
deduplicação na reindexação, busca híbrida explicada (TF-IDF denso + BM25 léxico) e exclusão por id_documento.
"""

import os
import re
import json
import hashlib
import collections
import numpy as np
from typing import List, Dict, Any, Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.ingestion import ChunkDocumento
from src.schemas import TrechoRecuperado

CAMINHO_INDICE_PADRAO = "indice/indice_vetorial.json"


class IndiceVetorial:
    """Índice vetorial persistente híbrido com suporte a metadados, deduplicação e exclusão."""

    def __init__(
        self,
        caminho_indice: Optional[str] = CAMINHO_INDICE_PADRAO,
        nome_modelo: str = "tfidf-bm25-hibrido-pt",
        dimensao: int = 512,
        persistir: bool = True,
    ):
        self.caminho_indice = caminho_indice
        self.nome_modelo = nome_modelo
        self.dimensao = dimensao
        self.persistir = persistir and bool(caminho_indice)
        self.versao_indice = "v2.0-empty"
        self.chunks: List[Dict[str, Any]] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matriz_vetores: Optional[np.ndarray] = None
        self.doc_tokens: List[List[str]] = []
        self.doc_lens: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_term_freqs: List[Dict[str, int]] = []
        self.doc_freqs: Dict[str, int] = collections.defaultdict(int)

        if self.persistir and self.caminho_indice:
            os.makedirs(os.path.dirname(self.caminho_indice) or ".", exist_ok=True)
            if os.path.exists(self.caminho_indice):
                self.carregar()

    def _atualizar_versao_indice(self) -> None:
        if not self.chunks:
            self.versao_indice = "v2.0-empty"
            return
        assinatura = "|".join(sorted(c.get("chunk_hash", "") for c in self.chunks))
        digest = hashlib.sha256(assinatura.encode("utf-8")).hexdigest()[:10]
        self.versao_indice = f"v2.0-{len(self.chunks)}c-{digest}"

    def adicionar_chunks(self, novos_chunks: List[ChunkDocumento]) -> int:
        """Adiciona chunks ao índice impedindo duplicações ao reindexar o mesmo documento (RF17 / T06)."""
        hashes_existentes = {c["chunk_hash"] for c in self.chunks}
        adicionados = 0

        for chk in novos_chunks:
            chk_dict = chk.to_dict() if hasattr(chk, "to_dict") else chk
            if chk_dict["chunk_hash"] not in hashes_existentes:
                self.chunks.append(chk_dict)
                hashes_existentes.add(chk_dict["chunk_hash"])
                adicionados += 1

        if adicionados > 0 or self.matriz_vetores is None:
            self._reconstruir_matriz()
            if self.persistir:
                self.salvar()

        return adicionados

    def _reconstruir_matriz(self) -> None:
        """Reconstrói a matriz vetorial e o modelo híbrido (TF-IDF denso + BM25 léxico) a partir dos chunks atuais."""
        self._atualizar_versao_indice()
        if not self.chunks:
            self.vectorizer = None
            self.matriz_vetores = None
            self.doc_tokens = []
            self.doc_lens = []
            self.avg_doc_len = 0.0
            self.doc_term_freqs = []
            self.doc_freqs = collections.defaultdict(int)
            return

        textos = [c["conteudo"] for c in self.chunks]
        self.vectorizer = TfidfVectorizer(
            max_features=self.dimensao,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        self.matriz_vetores = self.vectorizer.fit_transform(textos).toarray()

        # Configuração do Modelo BM25 Léxico Estrito
        self.doc_tokens = [re.findall(r"\b[a-záéíóúâêôãõç0-9]{3,}\b", c["conteudo"].lower()) for c in self.chunks]
        self.doc_lens = [len(toks) for toks in self.doc_tokens]
        self.avg_doc_len = sum(self.doc_lens) / max(1, len(self.doc_lens))
        self.doc_term_freqs = [collections.Counter(toks) for toks in self.doc_tokens]
        self.doc_freqs = collections.defaultdict(int)
        for tf in self.doc_term_freqs:
            for term in tf:
                self.doc_freqs[term] += 1

    def buscar_top_k(self, consulta: str, top_k: int = 3, limiar_minimo: float = 0.05) -> List[TrechoRecuperado]:
        """
        Executa busca híbrida (TF-IDF denso + BM25 léxico estrito) top-k com re-ranking lexical.
        Penaliza chunks que não contêm os termos específicos da consulta para mitigar alucinações.
        Retorna trechos com score de similaridade e distância (1 - similaridade).
        """
        if not self.chunks or self.vectorizer is None or self.matriz_vetores is None:
            return []

        vetor_consulta = self.vectorizer.transform([consulta]).toarray()
        similaridades = cosine_similarity(vetor_consulta, self.matriz_vetores)[0]

        # Cálculo do BM25 Léxico Estrito
        k1 = 1.5
        b = 0.75
        N = len(self.chunks)
        tokens_consulta = re.findall(r"\b[a-záéíóúâêôãõç0-9]{3,}\b", consulta.lower())
        bm25_scores = np.zeros(N)
        doc_freqs = getattr(self, "doc_freqs", {})
        doc_term_freqs = getattr(self, "doc_term_freqs", [])
        doc_lens = getattr(self, "doc_lens", [1] * N)
        avg_doc_len = getattr(self, "avg_doc_len", 1.0)

        for t in tokens_consulta:
            df = doc_freqs.get(t, 0)
            if df > 0:
                idf = np.log((N - df + 0.5) / (df + 0.5) + 1.0)
                for idx_chk in range(N):
                    freq = doc_term_freqs[idx_chk].get(t, 0) if idx_chk < len(doc_term_freqs) else 0
                    if freq > 0:
                        denom = freq + k1 * (1.0 - b + b * (doc_lens[idx_chk] / max(1.0, avg_doc_len)))
                        bm25_scores[idx_chk] += idf * (freq * (k1 + 1.0)) / denom

        max_bm25 = float(np.max(bm25_scores)) if len(bm25_scores) > 0 and np.max(bm25_scores) > 0 else 1.0
        bm25_norm = bm25_scores / max_bm25

        termos_consulta = set(re.findall(r"\b[a-záéíóúâêôãõç]{4,}\b", consulta.lower()))
        scores_ponderados = []
        for idx_chk in range(N):
            sim = float(similaridades[idx_chk])
            bm25_s = float(bm25_norm[idx_chk])
            texto_lower = self.chunks[idx_chk]["conteudo"].lower()
            bonus = 0.0
            termos_encontrados = 0
            for t in termos_consulta:
                raiz = t[:7] if len(t) >= 7 else t
                if t in texto_lower or (len(raiz) >= 6 and raiz in texto_lower):
                    bonus += 0.03
                    termos_encontrados += 1
                    if any(k in t for k in ["prorrog", "retifica", "adiad", "heteroidentifica"]):
                        bonus += 0.35

            # Penalidade se a consulta tem termos substantivos específicos e o chunk não contém nenhum deles
            penalidade = 0.0
            if len(termos_consulta) >= 2 and termos_encontrados == 0:
                penalidade = 0.25

            # Fusão Híbrida Balanceada: 50% Cosseno Denso + 50% BM25 Léxico Estrito + Bônus - Penalidade
            score_final = max(0.0, min(1.0, (0.5 * sim + 0.5 * bm25_s) + bonus - penalidade))
            scores_ponderados.append(score_final)

        indices_ordenados = np.argsort(scores_ponderados)[::-1]
        resultados: List[TrechoRecuperado] = []

        for idx in indices_ordenados[:top_k]:
            sim = float(similaridades[idx])
            sim_final = float(scores_ponderados[idx])
            if sim_final < limiar_minimo:
                continue

            chk = self.chunks[idx]
            distancia = float(max(0.0, 1.0 - sim))

            resultados.append(
                TrechoRecuperado(
                    documento_id=chk["documento_id"],
                    titulo=chk.get("titulo", "Documento Institucional"),
                    versao=chk.get("versao", "1.0"),
                    trecho_id=chk["trecho_id"],
                    pagina=chk.get("pagina"),
                    secao=chk.get("secao"),
                    conteudo=chk["conteudo"],
                    score_similaridade=round(sim_final, 4),
                    score_distancia=round(distancia, 4),
                    natureza=chk.get("natureza", "nao_classificado"),
                    fonte_original=chk.get("fonte_original", ""),
                    hash_arquivo=chk.get("hash_arquivo"),
                )
            )

        return resultados

    def excluir_documento(self, documento_id: str) -> int:
        """
        Exclui um documento e todos os seus vetores derivados do índice (RF17 / T14).
        Retorna a quantidade de chunks expurgados.
        """
        qtd_anterior = len(self.chunks)
        self.chunks = [c for c in self.chunks if c["documento_id"] != documento_id]
        removidos = qtd_anterior - len(self.chunks)

        if removidos > 0:
            self._reconstruir_matriz()
            if self.persistir:
                self.salvar()

        return removidos

    def salvar(self) -> None:
        """Persiste os metadados e chunks do índice em disco."""
        if not self.caminho_indice:
            return
        dados = {
            "nome_modelo": self.nome_modelo,
            "dimensao": self.dimensao,
            "versao_indice": self.versao_indice,
            "total_chunks": len(self.chunks),
            "chunks": self.chunks,
        }
        with open(self.caminho_indice, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)

    def carregar(self) -> None:
        """Carrega índice persistido em disco após reinício da aplicação."""
        if not self.caminho_indice or not os.path.exists(self.caminho_indice):
            return
        try:
            with open(self.caminho_indice, "r", encoding="utf-8") as f:
                dados = json.load(f)
            self.nome_modelo = dados.get("nome_modelo", self.nome_modelo)
            self.dimensao = dados.get("dimensao", self.dimensao)
            self.chunks = dados.get("chunks", [])
            self._reconstruir_matriz()
        except Exception:
            self.chunks = []
            self.vectorizer = None
            self.matriz_vetores = None
