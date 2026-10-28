"""
schemas.py - Contratos de Dados Estruturados e Validação (RF14)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Utiliza Pydantic v2 com validação estrita, representação de ausências por null,
lista rastreável de campos ausentes e verificação de regras de negócio.
"""

from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
import re
from datetime import datetime

CATEGORIAS_VALIDAS = [
    "Matrícula e Ingresso",
    "Documentação e Certidões",
    "Assistência Estudantil",
    "Cursos e Horários",
    "Outros / Informações Gerais",
    "revisão"
]

STATUS_RAG_VALIDOS = ["fundamentada", "sem_evidencia_suficiente", "conflito_de_fontes"]
POLARIDADES_VALIDAS = ["positiva", "negativa", "neutra", "indeterminada"]
DECISOES_HUMANAS_VALIDAS = ["pendente", "aprovada", "rejeitada", "revisar"]


class EntidadesExtraidas(BaseModel):
    pessoas: List[str] = Field(default_factory=list)
    orgaos: List[str] = Field(default_factory=list)
    locais: List[str] = Field(default_factory=list)
    datas: List[str] = Field(default_factory=list)
    protocolos: List[str] = Field(default_factory=list)


class ExtracaoFicha(BaseModel):
    """Contrato de dados formal da solicitação do cidadão (RF14/RF15)."""
    protocolo: Optional[str] = None
    data: Optional[str] = None
    solicitante: Optional[str] = None
    cpf: Optional[str] = None
    rg: Optional[str] = None
    data_nascimento: Optional[str] = None
    naturalidade: Optional[str] = None
    nome_mae: Optional[str] = None
    nome_pai: Optional[str] = None
    curso: Optional[str] = None
    eixo_tecnologico: Optional[str] = None
    carga_horaria: Optional[str] = None
    turno: Optional[str] = None
    inicio_curso: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    assunto: Optional[str] = None
    pedido: Optional[str] = None
    categoria: str = "Outros / Informações Gerais"
    entidades: EntidadesExtraidas = Field(default_factory=EntidadesExtraidas)
    resumo: str = ""
    campos_ausentes: List[str] = Field(default_factory=list)
    necessidade_revisao: bool = False

    @field_validator("categoria")
    @classmethod
    def validar_categoria(cls, v: str) -> str:
        if v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"Categoria '{v}' não pertence às categorias documentadas: {CATEGORIAS_VALIDAS}")
        return v

    @field_validator("data", "data_nascimento", "inicio_curso")
    @classmethod
    def validar_formato_data(cls, v: Optional[str]) -> Optional[str]:
        if not v or v in ("não localizado", "null", "None"):
            return None
        # Verifica formato dd/mm/aaaa ou aaaa-mm-dd e valida calendário real
        padrao_br = r"^\d{2}/\d{2}/\d{4}$"
        padrao_iso = r"^\d{4}-\d{2}-\d{2}$"
        if re.match(padrao_br, v):
            try:
                datetime.strptime(v, "%d/%m/%Y")
            except ValueError as e:
                raise ValueError(f"Data impossível ou inválida no calendário: {v}") from e
        elif re.match(padrao_iso, v):
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError as e:
                raise ValueError(f"Data impossível ou inválida no calendário: {v}") from e
        else:
            raise ValueError(f"Data com formato inválido: {v}")
        return v

    @model_validator(mode="after")
    def conferir_regras_negocio_e_ausencias(self) -> "ExtracaoFicha":
        # Mapeia quais campos essenciais são ausentes
        campos_verificar = [
            "protocolo", "data", "solicitante", "cpf", "rg",
            "data_nascimento", "naturalidade", "nome_mae", "nome_pai",
            "curso", "eixo_tecnologico", "carga_horaria", "turno",
            "inicio_curso", "email", "telefone", "assunto", "pedido"
        ]
        
        ausentes = []
        for campo in campos_verificar:
            valor = getattr(self, campo)
            if valor is None or valor in ("", "não localizado", "null"):
                setattr(self, campo, None)
                ausentes.append(campo)
        
        self.campos_ausentes = sorted(list(set(self.campos_ausentes + ausentes)))
        
        # Se solicitante, pedido ou curso forem nulos, marca necessidade de revisão
        if not self.solicitante or not self.pedido:
            self.necessidade_revisao = True
            if self.categoria not in ("revisão", "Outros / Informações Gerais"):
                self.categoria = "revisão"
                
        return self

    def para_interface_usuario(self) -> Dict[str, Any]:
        """Converte ausências (null) para o rótulo institucional 'não localizado' na UI."""
        dados = self.model_dump()
        for k, v in dados.items():
            if v is None and k not in ("entidades", "campos_ausentes", "necessidade_revisao"):
                dados[k] = "não localizado"
        return dados


class SolicitacaoEntrada(BaseModel):
    id: str
    tipo: Literal["texto", "audio", "ocr"] = "texto"
    subtipo: Optional[str] = "completa"
    canal: str = "web"
    protocolo: Optional[str] = None
    data: Optional[str] = None
    texto_original: str


class TrechoRecuperado(BaseModel):
    documento_id: str
    versao: str
    trecho_id: str
    pagina: Optional[int] = None
    secao: Optional[str] = None
    conteudo: str
    score_similaridade: float = 0.0
    score_distancia: float = 0.0


class RespostaRAG(BaseModel):
    pergunta: str
    resposta: str
    fontes: List[TrechoRecuperado] = Field(default_factory=list)
    status: Literal["fundamentada", "sem_evidencia_suficiente", "conflito_de_fontes"] = "fundamentada"
    divergencia_identificada: Optional[str] = None
    necessidade_revisao: bool = False
    citacoes_formatadas: List[str] = Field(default_factory=list)


class ClassificacaoSentimento(BaseModel):
    id: str
    polaridade: Literal["positiva", "negativa", "neutra", "indeterminada"]
    justificativa: str
    necessidade_revisao: bool = False
    confianca_estimada: float = Field(ge=0.0, le=1.0)


class DecisaoOperador(BaseModel):
    solicitacao_id: str
    decisao: Literal["pendente", "aprovada", "rejeitada", "revisar"]
    justificativa: str
    operador: str = "servidor_responsavel"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
