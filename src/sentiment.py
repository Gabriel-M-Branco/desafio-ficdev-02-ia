"""
sentiment.py - Classificação de Sentimentos e Agregação Determinística (RF22)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Classifica manifestações do cidadão em positiva, negativa, neutra ou indeterminada,
admitindo indeterminação para ironia, mensagens mistas e falta de contexto.
Calcula métricas agregadas por código determinístico, sem inferência psicológica.
"""

import re
from typing import List, Dict, Any, Tuple
from src.schemas import ClassificacaoSentimento

PALAVRAS_POSITIVAS = [
    "excelente", "muito bom", "ótimo", "otimo", "rápido", "rapido", "solícito", "solicito",
    "atenciosa", "atencioso", "parabéns", "parabens", "satisfeito", "educado", "prestativo"
]

PALAVRAS_NEGATIVAS = [
    "demora", "absurda", "péssima", "pessima", "descanso", "descaso", "horrível", "horrivel",
    "fora do ar", "reclamar", "errada", "perdi", "lentidão", "lentidao", "ninguém atende"
]

PADROES_IRONIA = [
    r"parabéns pelo sistema maravilhoso.*só precisei esperar",
    r"maravilha.*esperar",
    r"ótimo atendimento.*semanas"
]


def classificar_sentimento_avaliacao(
    id_aval: str,
    texto: str
) -> ClassificacaoSentimento:
    """
    Classifica uma mensagem do cidadão.
    Regra estrita: mensagens com ironia, sentimentos conflitantes ou mero protocolo
    são classificadas como 'indeterminada', com necessidade de revisão humana.
    """
    t_lower = texto.lower()

    # 1. Detecção de Ironia / Sarcasmo
    for padrao in PADROES_IRONIA:
        if re.search(padrao, t_lower):
            return ClassificacaoSentimento(
                id=id_aval,
                polaridade="indeterminada",
                justificativa="Presença de ironia/sarcasmo (elogio aparente seguido de forte crítica temporal).",
                necessidade_revisao=True,
                confianca_estimada=0.50
            )

    # 2. Detecção de Mensagens Mistas / Polares Opostas
    tem_elogio = any(p in t_lower for p in ["educado", "prestativo", "excelente"])
    tem_critica = any(p in t_lower for p in ["horrível", "horrivel", "lentidão", "lentidao", "terrível", "demora"])
    if tem_elogio and tem_critica:
        return ClassificacaoSentimento(
            id=id_aval,
            polaridade="indeterminada",
            justificativa="Mensagem mista contendo elogio ao servidor e crítica simultânea ao sistema/infraestrutura.",
            necessidade_revisao=True,
            confianca_estimada=0.55
        )

    # 3. Falta de Contexto Opinativo / Registro Factual Protocolar
    if ("registro de atendimento" in t_lower or "protocolo nº" in t_lower) and not any(p in t_lower for p in PALAVRAS_POSITIVAS + PALAVRAS_NEGATIVAS):
        return ClassificacaoSentimento(
            id=id_aval,
            polaridade="indeterminada",
            justificativa="Falta de contexto opinativo: mero registro protocolar numérico sem expressão de sentimento.",
            necessidade_revisao=True,
            confianca_estimada=0.50
        )

    # 4. Avaliação Positiva
    score_pos = sum(1 for p in PALAVRAS_POSITIVAS if p in t_lower)
    score_neg = sum(1 for p in PALAVRAS_NEGATIVAS if p in t_lower)

    if score_pos > 0 and score_neg == 0:
        return ClassificacaoSentimento(
            id=id_aval,
            polaridade="positiva",
            justificativa="Expressão inequívoca de satisfação e elogio ao atendimento.",
            necessidade_revisao=False,
            confianca_estimada=0.92
        )

    # 5. Avaliação Negativa
    if score_neg > 0 and score_pos == 0:
        return ClassificacaoSentimento(
            id=id_aval,
            polaridade="negativa",
            justificativa="Crítica expressa a falhas de serviço, lentidão ou canais inoperantes.",
            necessidade_revisao=False,
            confianca_estimada=0.90
        )

    # 6. Neutra (Factual, rotineira sem adjetivos avaliativos)
    return ClassificacaoSentimento(
        id=id_aval,
        polaridade="neutra",
        justificativa="Comunicação factual e descritiva dos trâmites regulares de atendimento.",
        necessidade_revisao=False,
        confianca_estimada=0.85
    )


def agregar_sentimentos_determinístico(
    classificacoes: List[ClassificacaoSentimento]
) -> Dict[str, Any]:
    """
    Agregação de dados calculada exclusivamente por código determinístico (RF22).
    Distingue a contagem matemática real da estimativa probabilística de cada item.
    """
    total = len(classificacoes)
    if total == 0:
        return {
            "total": 0,
            "distribuicao": {"positiva": 0, "negativa": 0, "neutra": 0, "indeterminada": 0},
            "percentuais": {"positiva": 0.0, "negativa": 0.0, "neutra": 0.0, "indeterminada": 0.0},
            "total_revisao": 0,
            "percentual_revisao": 0.0,
            "nota_metodologica": "Sem dados para agregação."
        }

    contagem = {"positiva": 0, "negativa": 0, "neutra": 0, "indeterminada": 0}
    revisoes = 0

    for c in classificacoes:
        pol = c.polaridade
        contagem[pol] = contagem.get(pol, 0) + 1
        if c.necessidade_revisao:
            revisoes += 1

    percentuais = {
        pol: round((qtd / total) * 100, 2)
        for pol, qtd in contagem.items()
    }

    return {
        "total": total,
        "distribuicao": contagem,
        "percentuais": percentuais,
        "total_revisao": revisoes,
        "percentual_revisao": round((revisoes / total) * 100, 2),
        "nota_metodologica": (
            "Contagens calculadas deterministicamente via Python. "
            "Atenção: Os índices de confiança declarados pelos modelos são estimativas não calibradas "
            "e não representam probabilidade matemática exata nem constituem pesquisa censitária da população."
        )
    }
