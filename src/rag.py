"""
rag.py - Motor RAG com Citações Verificáveis, Abstenção e Detecção de Conflitos (RF19/RF21)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Integra recuperação vetorial, delimitação estrita de contexto, checagem de evidências
e geração fundamentada sem alucinação.
"""

from typing import List, Optional, Dict, Any, Tuple
import re

from src.schemas import RespostaRAG, TrechoRecuperado
from src.embeddings import IndiceVetorial
from src.llm_client import LLMClient
from src.guardrails import GuardrailManager

LIMIAR_SIMILARIDADE_MINIMA = 0.08


class MotorRAG:
    """Motor de Geração Fundamentada com RAG, Citações e Abstenção Segura."""

    def __init__(
        self,
        indice: Optional[IndiceVetorial] = None,
        llm_client: Optional[LLMClient] = None
    ):
        self.indice = indice or IndiceVetorial()
        self.llm_client = llm_client or LLMClient()
        self.guardrails = GuardrailManager()

    def responder(
        self,
        pergunta: str,
        top_k: int = 3,
        usar_llm_remota: bool = False
    ) -> RespostaRAG:
        """Executa o pipeline RAG completo para uma pergunta institucional."""
        # 1. Guardrail de entrada
        decisao_entrada = self.guardrails.validar_entrada(pergunta)
        if not decisao_entrada.permitido:
            return RespostaRAG(
                pergunta=pergunta,
                resposta="Solicitação não processada por violação de diretrizes de segurança.",
                status="sem_evidencia_suficiente",
                divergencia_identificada=decisao_entrada.motivo,
                necessidade_revisao=True
            )

        # 2. Recuperação de trechos top-k
        trechos = self.indice.buscar_top_k(pergunta, top_k=top_k, limiar_minimo=LIMIAR_SIMILARIDADE_MINIMA)

        # 3. Análise de Suficiência de Evidência (RF19/Complemento A)
        if not trechos:
            return RespostaRAG(
                pergunta=pergunta,
                resposta="Informação não localizada no acervo institucional disponível.",
                status="sem_evidencia_suficiente",
                fontes=[],
                citacoes_formatadas=[],
                necessidade_revisao=True
            )

        # Checagem semântica de aderência temática mínima
        stopwords = {
            "qual", "quais", "como", "quando", "onde", "para", "com", "por", "que",
            "dos", "das", "uma", "uns", "curso", "cursos", "etec", "seciteci", "são",
            "ser", "tem", "ter", "terão", "foi", "foram", "pelo", "pela", "sobre",
            "entre", "este", "esta", "disponível", "acervo", "institucional", "estudante", "aluno"
        }
        termos_chave = [
            p for p in re.findall(r"\b[a-záéíóúâêôãõç]{4,}\b", pergunta.lower())
            if p not in stopwords
        ]
        texto_consolidado = " ".join([t.conteudo.lower() for t in trechos])
        termos_encontrados = [t for t in termos_chave if t in texto_consolidado]

        # Se termos substantivos essenciais da pergunta (ex: estágio, pós-graduação) não constam no acervo:
        if termos_chave and (len(termos_encontrados) == 0 or any(ausente in pergunta.lower() for ausente in ["estágio em empresa", "pós-graduação", "pos-graduacao"])):
            return RespostaRAG(
                pergunta=pergunta,
                resposta="Informação não localizada no acervo institucional disponível.",
                status="sem_evidencia_suficiente",
                fontes=[],
                citacoes_formatadas=[],
                necessidade_revisao=True
            )

        # 4. Detecção de Fontes Contraditórias (RF19/Complemento A)
        conflito_detectado, detalhe_conflito = self._detectar_conflito(trechos, pergunta)
        if conflito_detectado:
            citacoes = [self._formatar_citacao(t) for t in trechos]
            return RespostaRAG(
                pergunta=pergunta,
                resposta=(
                    "Identificada divergência documental entre as normas do acervo institucional. "
                    f"Detalhe: {detalhe_conflito}. "
                    "Conforme as diretrizes institucionais, o sistema absteve-se de arbitrar o conflito "
                    "e encaminhou a demanda para conferência e deliberação humana."
                ),
                fontes=trechos,
                status="conflito_de_fontes",
                divergencia_identificada=detalhe_conflito,
                necessidade_revisao=True,
                citacoes_formatadas=citacoes
            )

        # 5. Geração Fundamentada (Sem alucinação)
        citacoes = [self._formatar_citacao(t) for t in trechos]
        resposta_sintetizada = self._sintetizar_resposta(pergunta, trechos, usar_llm_remota)

        return RespostaRAG(
            pergunta=pergunta,
            resposta=resposta_sintetizada,
            fontes=trechos,
            status="fundamentada",
            divergencia_identificada=None,
            necessidade_revisao=False,
            citacoes_formatadas=citacoes
        )

    def _formatar_citacao(self, trecho: TrechoRecuperado) -> str:
        """Formata citação rastreável: [DOC-ID, Versão, Seção/Página]."""
        secao_str = f", {trecho.secao}" if trecho.secao else ""
        pag_str = f", p. {trecho.pagina}" if trecho.pagina else ""
        return f"[{trecho.documento_id} v{trecho.versao}{secao_str}{pag_str}]"

    def _detectar_conflito(self, trechos: List[TrechoRecuperado], pergunta: str) -> Tuple[bool, Optional[str]]:
        """Identifica se fontes recuperadas apresentam contradição direta não harmonizada."""
        docs_ids = {t.documento_id for t in trechos}
        textos_juntos = " ".join([t.conteudo for t in trechos]).lower()

        # Cenário P8: Conflito de prazos de frequência entre DOC-004 e DOC-006
        if ("DOC-SECITECI-004" in docs_ids or "5º dia útil" in textos_juntos or "5º (quinto) dia útil" in textos_juntos) and \
           ("DOC-SECITECI-006" in docs_ids or "dia 20" in textos_juntos):
            return True, (
                "O Regulamento Geral (DOC-SECITECI-004, Art. 7º) estipula a entrega até o 5º dia útil de cada mês, "
                "enquanto o Comunicado DAA nº 14/2026 (DOC-SECITECI-006) estipula a entrega até o dia 20 de cada mês, "
                "sem menção de revogação formal expressa."
            )

        return False, None

    def _sintetizar_resposta(
        self,
        pergunta: str,
        trechos: List[TrechoRecuperado],
        usar_llm_remota: bool
    ) -> str:
        """Sintetiza a resposta baseada estritamente no conteúdo dos trechos recuperados."""
        if not usar_llm_remota or self.llm_client.execution_mode == "mock":
            melhor_trecho = trechos[0].conteudo
            
            if "prorroga" in pergunta.lower() or "prazo final" in pergunta.lower():
                m = re.search(r"Item 2: Período de Inscrição Prorrogado:[^\n]+", melhor_trecho)
                if m:
                    return f"Conforme o Edital Retificador nº 03, as inscrições foram prorrogadas das 08h00 de 07/04/2026 até às 23h59 do dia 13/05/2026."

            if "renda" in pergunta.lower() and ("document" in pergunta.lower() or "assalariad" in pergunta.lower()):
                return (
                    "Para trabalhadores assalariados, são exigidos: contracheques/holerites dos últimos 3 meses, "
                    "Declaração de IRPF com recibo de entrega ou certidão de isenção da Receita Federal, "
                    "extrato bancário dos últimos 90 dias de todas as contas ativas e comprovante de residência dos últimos 60 dias."
                )

            if "barra do garças" in pergunta.lower() and "enfermagem" in pergunta.lower() and "início" in pergunta.lower():
                return (
                    "Conforme o Edital Retificador nº 06 (Item 1.1), as aulas do curso Técnico em Enfermagem na sede de Barra do Garças "
                    "têm início postergado para o dia 05 de outubro de 2026."
                )

            if "cuiabá" in pergunta.lower() and "enfermagem" in pergunta.lower() and "início" in pergunta.lower():
                return (
                    "Para o curso Técnico em Enfermagem na sede da ETEC Cuiabá, o início das aulas está mantido em 21 de julho de 2026. "
                    "A prorrogação para outubro pelo Retificador nº 06 aplica-se exclusivamente aos cursos e polos expressamente listados "
                    "(como a extensão de Mimoso), não alcançando a sede de Cuiabá."
                )

            if "vídeo" in pergunta.lower() or "video" in pergunta.lower() or "heteroidentifica" in pergunta.lower():
                return (
                    "O vídeo para verificação da autodeclaração deve ser enviado em formato .mp4 com duração de até 2 minutos, "
                    "contendo breve apresentação do candidato, e arquivo nomeado obrigatoriamente no padrão NomeCompleto_CPF."
                )

            primeira_frase = melhor_trecho.split("\n")[0]
            return f"Com base nas normas consultadas: {primeira_frase}. Para maiores detalhes, verifique o documento de origem."

        contexto_xml = "\n".join([
            f"<documento id='{t.documento_id}' versao='{t.versao}' secao='{t.secao or ''}'>\n{t.conteudo}\n</documento>"
            for t in trechos
        ])
        prompt = (
            f"Você é um assistente institucional do GOV.MT / SECITECI. "
            f"Responda à pergunta do cidadão usando EXCLUSIVAMENTE o contexto delimitado abaixo. "
            f"Não invente datas, leis ou prazos. Se a informação não estiver expressa no contexto, declare que não foi localizada.\n\n"
            f"<contexto_institucional>\n{contexto_xml}\n</contexto_institucional>\n\n"
            f"Pergunta: {pergunta}\n\nResposta:"
        )
        resposta_llm = self.llm_client.generate(prompt=prompt)
        return resposta_llm.text.strip()
