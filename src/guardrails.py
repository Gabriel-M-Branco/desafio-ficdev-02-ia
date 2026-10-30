"""
guardrails.py - Moderação em Camadas, Segurança e Limites de Execução (RF16)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Controla tipo/tamanho de arquivo, entrada, documentos recuperados do corpus (ADV-02),
saída do modelo, proteção de segredos e limite máximo de chamadas/tokens por execução.
"""

import re
import os
from typing import Dict, Any, Tuple, Optional, List
from pydantic import BaseModel

TAMANHO_MAX_TEXTO = 8000
TAMANHO_MIN_TEXTO = 5
TAMANHO_MAX_ARQUIVO_BYTES = 10 * 1024 * 1024  # 10 MB
EXTENSOES_ARQUIVO_PERMITIDAS = {".txt", ".pdf", ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".ogg", ".m4a"}
MAX_CHAMADAS_POR_EXECUCAO = 3
MAX_TOKENS_POR_EXECUCAO = 6000
TIMEOUT_PADRAO_SEGUNDOS = 30
MAX_TENTATIVAS_REPETICAO = 1

# Padrões suspeitos para detecção de prompt injection (direta e indireta no corpus) e jailbreak
PADROES_INJECAO = [
    r"(?:ignore|desconsidere)\s+(?:(?:todas?|as|os|anteriores)\s+)*(?:instru[cç][oõ]es|regras|diretrizes|comandos)(?:\s+anteriores)?",
    r"ignore\s+(?:all\s+)?previous\s+(?:instructions|rules)",
    r"ignore\s+(all\s+)?(previous\s+)?(instructions|rules|directions)",
    r"ignore\s+(as\s+)?(normas|regras|instruções|diretrizes)",
    r"desconsidere\s+(todas\s+as\s+)?(instruções|regras|diretrizes|normas)",
    r"system\s*override",
    r"instrucao_interna",
    r"instrução_interna",
    r"modo\s+(administrador|dan|developer|root)",
    r"vaze\s+(as\s+|o\s+)?(chaves|senhas|tokens|diretrizes|prompts|prompt)",
    r"imprima\s+(o\s+)?(prompt|hf_token|openrouter|openai_api_key|api_key)",
    r"revele\s+(as\s+)?(chaves|instruções|variáveis)",
    r"hacked\s+by",
    r"jailbreak",
]

# Padroes discriminatorios, ilicitos ou de odio incompativeis com principios constitucionais e institucionais (RF16)
PADROES_DISCRIMINATORIOS_OU_ILICITOS = [
    r"\bsegrega[cç][aã]o\b",
    r"\bapartheid\b",
    r"\bsupremacia\b",
    r"\bneonazis\w*\b",
    r"\bdiscrimina[cç][aã]o\s+racial\b",
]

PALAVRAS_CHAVE_SEGREDOS = [
    "hf_token", "openrouter_api_key", "openai_api_key", "bearer ", "authorization:",
    "secret_key", "password", "api_key", "credencial",
]

ESCOPO_PALAVRAS_CHAVE = [
    "etec", "seciteci", "curso", "matrícula", "matricula", "inscrição", "inscricao",
    "auxílio", "auxilio", "permanência", "permanencia", "edital", "vagas", "cota",
    "frequência", "frequencia", "renda", "transporte", "alimentação", "alimentacao",
    "conferência", "conferencia", "sorteio", "classificado", "aprovado", "recurso",
    "cuiabá", "cuiaba", "barra do garças", "barra do garcas", "cáceres", "caceres",
    "heteroidentificação", "heteroidentificacao", "cronograma",
]


class DecisaoGuardrail(BaseModel):
    permitido: bool
    status: str  # "permitir", "bloquear", "revisar"
    motivo: str
    texto_sanitizado: str
    alerta_seguranca: bool = False


class GuardrailManager:
    """Gerenciador de Guardrails em camadas para arquivo, entrada, contexto RAG, saída e limites."""

    def __init__(self, escopo_estrito: bool = True, max_chamadas: int = MAX_CHAMADAS_POR_EXECUCAO):
        self.escopo_estrito = escopo_estrito
        self.max_chamadas = max_chamadas
        self.chamadas_na_execucao = 0
        self.tokens_na_execucao = 0

    def resetar_contador_execucao(self) -> None:
        """Reinicia o contador de chamadas e tokens para uma nova execução."""
        self.chamadas_na_execucao = 0
        self.tokens_na_execucao = 0

    def registrar_chamada_modelo(self, tokens_estimados: int = 0) -> DecisaoGuardrail:
        """RF16 item 5 / T05: Aplica limite máximo de chamadas e tokens por execução."""
        if self.chamadas_na_execucao >= self.max_chamadas:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=(
                    f"Limite máximo de chamadas por execução atingido "
                    f"({self.chamadas_na_execucao}/{self.max_chamadas})."
                ),
                texto_sanitizado="",
                alerta_seguranca=True,
            )
        if self.tokens_na_execucao + tokens_estimados > MAX_TOKENS_POR_EXECUCAO:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=(
                    f"Limite máximo de tokens por execução excedido "
                    f"({self.tokens_na_execucao + tokens_estimados} > {MAX_TOKENS_POR_EXECUCAO})."
                ),
                texto_sanitizado="",
                alerta_seguranca=True,
            )
        self.chamadas_na_execucao += 1
        self.tokens_na_execucao += max(0, tokens_estimados)
        return DecisaoGuardrail(
            permitido=True,
            status="permitir",
            motivo=f"Chamada {self.chamadas_na_execucao}/{self.max_chamadas} autorizada.",
            texto_sanitizado="",
        )

    def validar_arquivo(self, nome_arquivo: str, tamanho_bytes: int) -> DecisaoGuardrail:
        """RF16 item 1 / T05: Valida extensão e tamanho máximo de arquivo enviado."""
        if not nome_arquivo:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Nome de arquivo vazio ou inválido.",
                texto_sanitizado="",
            )
        ext = os.path.splitext(nome_arquivo.lower())[1]
        if ext not in EXTENSOES_ARQUIVO_PERMITIDAS:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Tipo de arquivo '{ext}' não permitido. Permitidos: {sorted(EXTENSOES_ARQUIVO_PERMITIDAS)}.",
                texto_sanitizado="",
                alerta_seguranca=True,
            )
        if tamanho_bytes <= 0:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Arquivo vazio (0 bytes).",
                texto_sanitizado="",
            )
        if tamanho_bytes > TAMANHO_MAX_ARQUIVO_BYTES:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Arquivo excede o tamanho máximo permitido ({tamanho_bytes} > {TAMANHO_MAX_ARQUIVO_BYTES} bytes).",
                texto_sanitizado="",
                alerta_seguranca=True,
            )
        return DecisaoGuardrail(
            permitido=True,
            status="permitir",
            motivo="Arquivo dentro dos parâmetros institucionais de tipo e tamanho.",
            texto_sanitizado=nome_arquivo,
        )

    def validar_entrada(self, texto: str, tipo: str = "texto") -> DecisaoGuardrail:
        """Aplica validação de comprimento, integridade, injeção e escopo na entrada."""
        if not texto or not isinstance(texto, str):
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Entrada nula ou tipo não textual.",
                texto_sanitizado="",
            )

        tamanho = len(texto.strip())
        if tamanho < TAMANHO_MIN_TEXTO:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Entrada excessivamente curta ({tamanho} caracteres). Mínimo: {TAMANHO_MIN_TEXTO}.",
                texto_sanitizado=texto,
            )

        if tamanho > TAMANHO_MAX_TEXTO:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Entrada excede comprimento máximo permitido ({tamanho} > {TAMANHO_MAX_TEXTO} caracteres).",
                texto_sanitizado=texto[:TAMANHO_MAX_TEXTO],
            )

        # 1. Detecção de tentativa de extração de credenciais ou injeção adversária
        texto_lower = texto.lower()
        for padrao in PADROES_INJECAO:
            if re.search(padrao, texto_lower):
                return DecisaoGuardrail(
                    permitido=False,
                    status="bloquear",
                    motivo="Tentativa de injeção de prompt ou quebra de diretrizes detectada (RF16).",
                    texto_sanitizado=self.mascarar_conteudo_sensivel(texto),
                    alerta_seguranca=True,
                )

        # 1.1 Detecção de termos discriminatórios, ilícitos ou incompatíveis com princípios institucionais
        for padrao in PADROES_DISCRIMINATORIOS_OU_ILICITOS:
            if re.search(padrao, texto_lower):
                return DecisaoGuardrail(
                    permitido=False,
                    status="bloquear",
                    motivo="Entrada bloqueada por conter termo discriminatório, ilícito ou incompatível com os princípios institucionais (RF16).",
                    texto_sanitizado=self.mascarar_conteudo_sensivel(texto),
                    alerta_seguranca=True,
                )

        # 2. Tentativa direta de obter segredos
        if any(segredo in texto_lower for segredo in ["hf_token", "openrouter_api_key", "openai_api_key", "print system prompt"]):
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Tentativa de extração de credenciais protegidas bloqueada.",
                texto_sanitizado="[BLOQUEADO POR POLÍTICA DE SEGURANÇA]",
                alerta_seguranca=True,
            )

        # 3. Verificação de escopo temático institucional (fora de escopo gera 'revisar')
        if self.escopo_estrito and not any(termo in texto_lower for termo in ESCOPO_PALAVRAS_CHAVE):
            return DecisaoGuardrail(
                permitido=True,
                status="revisar",
                motivo="Manifestação aparentemente fora do escopo institucional usual. Encaminhado para triagem.",
                texto_sanitizado=self.mascarar_conteudo_sensivel(texto),
            )

        return DecisaoGuardrail(
            permitido=True,
            status="permitir",
            motivo="Entrada validada com sucesso.",
            texto_sanitizado=self.mascarar_conteudo_sensivel(texto),
        )

    def isolar_conteudo_nao_confiavel(self, conteudo: str) -> str:
        """Envolve conteúdo externo no envelope semântico XML anti-injeção (RF03/RF16)."""
        conteudo_limpo = conteudo.replace("</conteudo_nao_confiavel>", "[TAG_NEUTRALIZADA]")
        return f"<conteudo_nao_confiavel>\n{conteudo_limpo}\n</conteudo_nao_confiavel>"

    def sanitizar_documento_recuperado(self, conteudo_chunk: str, documento_id: str = "DOC") -> Tuple[bool, str, Optional[str]]:
        """
        RF16 item 2 / T04 (ADV-02): Isola documentos recuperados do corpus como conteúdo
        não confiável e neutraliza instruções maliciosas inseridas no acervo.
        Retorna (detectou_injecao, texto_isolado_limpo, motivo_alerta).
        """
        texto_limpo = conteudo_chunk.replace("</documento_recuperado>", "[TAG_DOC_NEUTRALIZADA]")
        detectou_injecao = False
        motivo = None

        # Remove blocos explícitos de [INSTRUCAO_INTERNA: ...] ou comandos imperativos maliciosos
        if re.search(r"\[INSTRU[CÇ][AÃ]O_INTERNA:.*?\]", texto_limpo, flags=re.I | re.S):
            detectou_injecao = True
            motivo = f"Instrução maliciosa indireta neutralizada no documento {documento_id} (ADV-02)."
            texto_limpo = re.sub(
                r"\[INSTRU[CÇ][AÃ]O_INTERNA:.*?\]",
                "[TRECHO_MALICIOSO_REMOVIDO_POR_GUARDRAIL]",
                texto_limpo,
                flags=re.I | re.S,
            )

        for padrao in PADROES_INJECAO:
            if re.search(padrao, texto_limpo, flags=re.I):
                detectou_injecao = True
                motivo = motivo or f"Padrão de prompt injection indireta neutralizado no documento {documento_id}."
                texto_limpo = re.sub(padrao, "[COMANDO_BLOQUEADO]", texto_limpo, flags=re.I)

        envelope = f'<documento_recuperado id="{documento_id}">\n{texto_limpo.strip()}\n</documento_recuperado>'
        return detectou_injecao, envelope, motivo

    def mascarar_conteudo_sensivel(self, texto: str) -> str:
        """Remove ou mascara credenciais, tokens, chaves reais e PII em textos e logs."""
        mascarado = texto
        mascarado = re.sub(r"hf_[A-Za-z0-9]{12,}", "[TOKEN_HF_MASCARADO]", mascarado)
        mascarado = re.sub(r"sk-or-[A-Za-z0-9\-_]{12,}", "[TOKEN_OPENROUTER_MASCARADO]", mascarado)
        mascarado = re.sub(r"sk-[A-Za-z0-9\-_]{12,}", "[TOKEN_OPENAI_MASCARADO]", mascarado)
        mascarado = re.sub(r"Bearer\s+[A-Za-z0-9\-_\.]{12,}", "Bearer [TOKEN_MASCARADO]", mascarado, flags=re.I)

        # Mascara CPFs reais para proteção LGPD (RF12 / RF21)
        mascarado = re.sub(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b", r"\1.***.***-\4", mascarado)
        return mascarado

    def filtrar_saida_modelo(self, resposta_texto: str) -> Tuple[bool, str, Optional[str]]:
        """Garante que a saída do modelo não contenha credenciais ou comandos subvertidos."""
        texto_lower = resposta_texto.lower()
        for palavra in PALAVRAS_CHAVE_SEGREDOS:
            if palavra in texto_lower:
                return (
                    False,
                    "[RESPOSTA RETIDA: Detecção de tentativa de vazamento de credencial]",
                    "Vazamento de segredo evitado na camada de saída.",
                )
        if re.search(r"\b(?:hf_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9\-_]{12,})\b", resposta_texto):
            return (
                False,
                "[RESPOSTA RETIDA: Padrão de chave de API detectado na saída]",
                "Chave de API bloqueada na camada de saída.",
            )
        return True, resposta_texto, None
