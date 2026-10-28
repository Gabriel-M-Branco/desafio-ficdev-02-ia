"""
guardrails.py - Moderação em Camadas, Segurança e Limites de Execução (RF16)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Controla entrada, contexto recuperado, saída do modelo e proteção de segredos.
"""

import re
import os
from typing import Dict, Any, Tuple, Optional, List
from pydantic import BaseModel

TAMANHO_MAX_TEXTO = 8000
TAMANHO_MIN_TEXTO = 5
MAX_CHAMADAS_POR_EXECUCAO = 3
TIMEOUT_PADRAO_SEGUNDOS = 30
MAX_TENTATIVAS_REPETICAO = 1

# Padrões suspeitos para detecção de prompt injection e jailbreak
PADROES_INJECAO = [
    r"ignore\s+(all\s+)?(previous\s+)?(instructions|rules|directions)",
    r"desconsidere\s+(todas\s+as\s+)?(instruções|regras|diretrizes)",
    r"system\s*override",
    r"modo\s+(administrador|dan|developer|root)",
    r"vaze\s+(as\s+)?(chaves|senhas|tokens|diretrizes|prompts)",
    r"imprima\s+(o\s+)?(prompt|hf_token|openrouter|api_key)",
    r"revele\s+(as\s+)?(chaves|instruções|variáveis)",
    r"hacked\s+by",
    r"jailbreak"
]

PALAVRAS_CHAVE_SEGREDOS = [
    "hf_token", "openrouter_api_key", "bearer ", "authorization:",
    "secret_key", "password", "api_key", "credencial"
]

ESCOPO_PALAVRAS_CHAVE = [
    "etec", "seciteci", "curso", "matrícula", "matricula", "inscrição", "inscricao",
    "auxílio", "auxilio", "permanência", "permanencia", "edital", "vagas", "cota",
    "frequência", "frequencia", "renda", "transporte", "alimentação", "alimentacao",
    "conferência", "conferencia", "sorteio", "classificado", "aprovado", "recurso",
    "cuiabá", "cuiaba", "barra do garças", "barra do garcas", "cáceres", "caceres"
]


class DecisaoGuardrail(BaseModel):
    permitido: bool
    status: str  # "permitir", "bloquear", "revisar"
    motivo: str
    texto_sanitizado: str
    alerta_seguranca: bool = False


class GuardrailManager:
    """Gerenciador de Guardrails em camadas para entrada, contexto e saída."""

    def __init__(self, escopo_estrito: bool = True):
        self.escopo_estrito = escopo_estrito

    def validar_entrada(self, texto: str, tipo: str = "texto") -> DecisaoGuardrail:
        """Aplica validação de comprimento, integridade, injeção e escopo na entrada."""
        if not texto or not isinstance(texto, str):
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Entrada nula ou tipo não textual.",
                texto_sanitizado=""
            )

        tamanho = len(texto.strip())
        if tamanho < TAMANHO_MIN_TEXTO:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Entrada excessivamente curta ({tamanho} caracteres). Mínimo: {TAMANHO_MIN_TEXTO}.",
                texto_sanitizado=texto
            )

        if tamanho > TAMANHO_MAX_TEXTO:
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo=f"Entrada excede comprimento máximo permitido ({tamanho} > {TAMANHO_MAX_TEXTO} caracteres).",
                texto_sanitizado=texto[:TAMANHO_MAX_TEXTO]
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
                    alerta_seguranca=True
                )

        # 2. Tentativa direta de obter segredos
        if any(segredo in texto_lower for segredo in ["hf_token", "openrouter_api_key", "print system prompt"]):
            return DecisaoGuardrail(
                permitido=False,
                status="bloquear",
                motivo="Tentativa de extração de credenciais protegidas bloqueada.",
                texto_sanitizado="[BLOQUEADO POR POLÍTICA DE SEGURANÇA]",
                alerta_seguranca=True
            )

        # 3. Verificação de escopo temático institucional (avaliação flexível: fora de escopo gera 'revisar')
        if self.escopo_estrito and not any(termo in texto_lower for termo in ESCOPO_PALAVRAS_CHAVE):
            # Se não contém nenhuma palavra do domínio ETEC/SECITECI
            return DecisaoGuardrail(
                permitido=True,
                status="revisar",
                motivo="Manifestação aparentemente fora do escopo institucional usual. Encaminhado para triagem.",
                texto_sanitizado=self.mascarar_conteudo_sensivel(texto)
            )

        return DecisaoGuardrail(
            permitido=True,
            status="permitir",
            motivo="Entrada validada com sucesso.",
            texto_sanitizado=self.mascarar_conteudo_sensivel(texto)
        )

    def isolar_conteudo_nao_confiavel(self, conteudo: str) -> str:
        """Envolve conteúdo externo no envelope semântico XML anti-injeção (RF03/RF16)."""
        # Neutraliza fechamentos maliciosos do envelope
        conteudo_limpo = conteudo.replace("</conteudo_nao_confiavel>", "[TAG_NEUTRALIZADA]")
        return f"<conteudo_nao_confiavel>\n{conteudo_limpo}\n</conteudo_nao_confiavel>"

    def mascarar_conteudo_sensivel(self, texto: str) -> str:
        """Remove ou mascara credenciais, tokens e chaves reais em textos e logs."""
        mascarado = texto
        # Mascara padrões comuns de chaves HF (hf_...) e OpenRouter (sk-or-...)
        mascarado = re.sub(r"hf_[A-Za-z0-9]{20,}", "[TOKEN_HF_MASCARADO]", mascarado)
        mascarado = re.sub(r"sk-or-[A-Za-z0-9\-_]{20,}", "[TOKEN_OPENROUTER_MASCARADO]", mascarado)
        mascarado = re.sub(r"Bearer\s+[A-Za-z0-9\-_\.]{20,}", "Bearer [TOKEN_MASCARADO]", mascarado, flags=re.I)
        
        # Mascara CPFs reais para proteção LGPD (RF12)
        mascarado = re.sub(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b", r"\1.***.***-\4", mascarado)
        return mascarado

    def filtrar_saida_modelo(self, resposta_texto: str) -> Tuple[bool, str, Optional[str]]:
        """Garante que a saída do modelo não contenha credenciais ou comandos subvertidos."""
        texto_lower = resposta_texto.lower()
        for palavra in PALAVRAS_CHAVE_SEGREDOS:
            if palavra in texto_lower:
                return False, "[RESPOSTA RETIDA: Detecção de tentativa de vazamento de credencial]", "Vazamento de segredo evitado na camada de saída."
        return True, resposta_texto, None
