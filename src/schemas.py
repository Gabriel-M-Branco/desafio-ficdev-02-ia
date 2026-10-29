"""
schemas.py - Contratos de Dados Estruturados e Validação (RF14)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Utiliza Pydantic v2 com validação estrita (extra='forbid'), representação de ausências por null,
lista rastreável de campos ausentes, separação literal vs. inferido e verificação de coerência factual.
"""

from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
import json
import re
from datetime import datetime

CATEGORIAS_VALIDAS = [
    "Matrícula e Ingresso",
    "Documentação e Certidões",
    "Assistência Estudantil",
    "Cursos e Horários",
    "Outros / Informações Gerais",
    "inscrição",
    "matrícula",
    "cronograma",
    "heteroidentificação",
    "assistência estudantil",
    "revisão",
]

STATUS_RAG_VALIDOS = ["fundamentada", "sem_evidencia_suficiente", "conflito_de_fontes"]
POLARIDADES_VALIDAS = ["positiva", "negativa", "neutra", "indeterminada"]
DECISOES_HUMANAS_VALIDAS = ["pendente", "aprovada", "rejeitada", "revisar"]


class EntidadesExtraidas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pessoas: List[str] = Field(default_factory=list)
    orgaos: List[str] = Field(default_factory=list)
    locais: List[str] = Field(default_factory=list)
    datas: List[str] = Field(default_factory=list)
    protocolos: List[str] = Field(default_factory=list)


class ExtracaoFicha(BaseModel):
    """Contrato de dados formal da solicitação do cidadão (RF14/RF15)."""
    model_config = ConfigDict(extra="forbid")

    versao_esquema: str = "2.0.0"
    protocolo: Optional[str] = None
    data: Optional[str] = None
    solicitante: Optional[str] = None
    cpf: Optional[str] = None
    rg: Optional[str] = None
    orgao_expedidor: Optional[str] = None
    uf: Optional[str] = None
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
    informacoes_inferidas: Dict[str, Any] = Field(default_factory=dict)
    resumo: str = ""
    campos_ausentes: List[str] = Field(default_factory=list)
    necessidade_revisao: bool = False
    texto_original_referencia: Optional[str] = Field(default=None, exclude=True)

    @field_validator("categoria")
    @classmethod
    def validar_categoria(cls, v: str) -> str:
        if not isinstance(v, str) or v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"Categoria '{v}' não pertence às categorias documentadas: {CATEGORIAS_VALIDAS}")
        return v

    @field_validator("cpf")
    @classmethod
    def validar_formato_cpf(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("CPF deve ser uma string ou null.")
        v_limpo = v.strip()
        if not v_limpo or v_limpo in ("não localizado", "null", "None"):
            return None
        if re.match(r"^\d{9}-\d{2}$", v_limpo):
            digitos = v_limpo.replace("-", "")
            v_limpo = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        if not re.match(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$", v_limpo):
            raise ValueError(f"CPF com formato inválido: {v}")
        return v_limpo

    @field_validator("data", "data_nascimento", "inicio_curso")
    @classmethod
    def validar_formato_data(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Data deve ser string no formato dd/mm/aaaa ou null.")
        if not v or v in ("não localizado", "null", "None"):
            return None
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
        campos_verificar = [
            "protocolo", "data", "solicitante", "cpf", "rg",
            "orgao_expedidor", "uf",
            "data_nascimento", "naturalidade", "nome_mae", "nome_pai",
            "curso", "eixo_tecnologico", "carga_horaria", "turno",
            "inicio_curso", "email", "telefone", "assunto", "pedido"
        ]

        ausentes = []
        for campo in campos_verificar:
            valor = getattr(self, campo)
            if valor is None or valor in ("", "não localizado", "null", "em branco"):
                setattr(self, campo, None)
                ausentes.append(campo)

        self.campos_ausentes = sorted(list(set(self.campos_ausentes + ausentes)))

        # Verificação de coerência factual com o texto original quando fornecido (RF14 / T02)
        if self.texto_original_referencia:
            ref_norm = re.sub(r"\s+", " ", self.texto_original_referencia).lower()
            ref_digitos = re.sub(r"\D", "", self.texto_original_referencia)

            if self.protocolo:
                prot_digitos = re.sub(r"\D", "", self.protocolo)
                if self.protocolo.lower() not in ref_norm and prot_digitos not in ref_digitos:
                    raise ValueError(
                        f"Coerência violada (T02): protocolo '{self.protocolo}' não está presente no texto original."
                    )
            if self.cpf:
                cpf_digitos = re.sub(r"\D", "", self.cpf)
                if cpf_digitos not in ref_digitos:
                    raise ValueError(
                        f"Coerência violada (T02): CPF '{self.cpf}' não está presente no texto original."
                    )
            if self.solicitante:
                primeiro_nome = self.solicitante.split()[0].lower()
                if primeiro_nome not in ref_norm:
                    raise ValueError(
                        f"Coerência violada (T02): solicitante '{self.solicitante}' não está presente no texto original."
                    )

        # Regra de negócio: se solicitante ou pedido forem nulos, marca necessidade de revisão
        if not self.solicitante or not self.pedido:
            self.necessidade_revisao = True
            if self.categoria not in ("revisão", "Outros / Informações Gerais"):
                self.categoria = "revisão"

        return self

    def separar_literal_e_inferido(self) -> Dict[str, Any]:
        """Separa explicitamente os campos extraídos literalmente dos inferidos (RF15 item 3)."""
        campos_literais = {
            "protocolo": self.protocolo,
            "data": self.data,
            "solicitante": self.solicitante,
            "cpf": self.cpf,
            "rg": self.rg,
            "orgao_expedidor": self.orgao_expedidor,
            "uf": self.uf,
            "data_nascimento": self.data_nascimento,
            "naturalidade": self.naturalidade,
            "nome_mae": self.nome_mae,
            "nome_pai": self.nome_pai,
            "curso": self.curso,
            "eixo_tecnologico": self.eixo_tecnologico,
            "carga_horaria": self.carga_horaria,
            "turno": self.turno,
            "inicio_curso": self.inicio_curso,
            "email": self.email,
            "telefone": self.telefone,
            "pedido": self.pedido,
            "entidades": self.entidades.model_dump(),
        }
        campos_inferidos = {
            "categoria": self.categoria,
            "assunto": self.assunto,
            "resumo": self.resumo,
            "necessidade_revisao": self.necessidade_revisao,
            **self.informacoes_inferidas,
        }
        return {
            "extracao_literal": campos_literais,
            "informacao_inferida": campos_inferidos,
            "campos_ausentes": self.campos_ausentes,
        }

    def para_interface_usuario(self) -> Dict[str, Any]:
        """Converte ausências (null) para o rótulo institucional 'não localizado' na UI."""
        dados = self.model_dump()
        for k, v in dados.items():
            if v is None and k not in ("entidades", "informacoes_inferidas", "campos_ausentes", "necessidade_revisao"):
                dados[k] = "não localizado"
        return dados


def comparar_json_sintatico_vs_esquema(payload_json: str) -> Dict[str, Any]:
    """
    RF14 item 3 / T01: Compara, em um mesmo caso, JSON apenas sintático (json.loads)
    e saída validada por esquema (ExtracaoFicha), diferenciando:
    - chave_extra (extra_forbidden)
    - tipo_incorreto (string_type / list_type / bool_type / int_type)
    - campo_obrigatorio_ausente (missing)
    - regra_negocio_violada (value_error)
    """
    resultado: Dict[str, Any] = {
        "json_sintatico_valido": False,
        "esquema_valido": False,
        "chaves_extras": [],
        "tipos_incorretos": [],
        "campos_obrigatorios_ausentes": [],
        "erros_regras_negocio": [],
    }
    try:
        dados = json.loads(payload_json)
        resultado["json_sintatico_valido"] = isinstance(dados, dict)
        if not isinstance(dados, dict):
            return resultado
    except Exception as exc:
        resultado["erro_sintatico"] = str(exc)
        return resultado

    # Verifica campos essenciais de um contrato estrito (ex.: solicitante, pedido, categoria)
    for obrigatorio in ("solicitante", "pedido", "categoria"):
        if obrigatorio not in dados:
            resultado["campos_obrigatorios_ausentes"].append(obrigatorio)

    try:
        ExtracaoFicha.model_validate(dados)
        if not resultado["campos_obrigatorios_ausentes"]:
            resultado["esquema_valido"] = True
    except ValidationError as err:
        for e in err.errors():
            tipo_erro = e.get("type", "")
            loc = ".".join(str(x) for x in e.get("loc", []))
            if "extra_forbidden" in tipo_erro:
                resultado["chaves_extras"].append(loc)
            elif "missing" in tipo_erro:
                if loc not in resultado["campos_obrigatorios_ausentes"]:
                    resultado["campos_obrigatorios_ausentes"].append(loc)
            elif "value_error" in tipo_erro:
                resultado["erros_regras_negocio"].append(f"{loc}: {e.get('msg')}")
            else:
                resultado["tipos_incorretos"].append(f"{loc} ({tipo_erro})")

    return resultado


class SolicitacaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: Literal["texto", "audio", "ocr"] = "texto"
    subtipo: Optional[str] = "completa"
    canal: str = "web"
    protocolo: Optional[str] = None
    data: Optional[str] = None
    texto_original: str


class TrechoRecuperado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documento_id: str
    titulo: Optional[str] = None
    versao: str
    trecho_id: str
    pagina: Optional[int] = None
    secao: Optional[str] = None
    conteudo: str
    score_similaridade: float = 0.0
    score_distancia: float = 0.0
    hash_arquivo: Optional[str] = None
    configuracao: Optional[str] = None
    chunk_hash: Optional[str] = None


class RespostaRAG(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pergunta: str
    resposta: str
    fontes: List[TrechoRecuperado] = Field(default_factory=list)
    status: Literal["fundamentada", "sem_evidencia_suficiente", "conflito_de_fontes"] = "fundamentada"
    divergencia_identificada: Optional[str] = None
    necessidade_revisao: bool = False
    citacoes_formatadas: List[str] = Field(default_factory=list)
    minuta_institucional: Optional[str] = None
    modo_geracao: str = "extrator_fundamentado_local"

    @field_validator("fontes", mode="before")
    @classmethod
    def _converter_fontes(cls, v):
        if not isinstance(v, list):
            return v
        res = []
        for x in v:
            if isinstance(x, TrechoRecuperado):
                res.append(x)
            elif isinstance(x, dict):
                res.append(TrechoRecuperado.model_validate(x))
            elif hasattr(x, "documento_id"):
                data = {
                    "documento_id": getattr(x, "documento_id", ""),
                    "titulo": getattr(x, "titulo", "Documento Institucional"),
                    "versao": getattr(x, "versao", "1.0"),
                    "trecho_id": getattr(x, "trecho_id", ""),
                    "pagina": getattr(x, "pagina", 1),
                    "secao": getattr(x, "secao", None),
                    "conteudo": getattr(x, "conteudo", ""),
                    "score_similaridade": getattr(x, "score_similaridade", 0.0),
                    "score_distancia": getattr(x, "score_distancia", 0.0),
                    "hash_arquivo": getattr(x, "hash_arquivo", None),
                    "configuracao": getattr(x, "configuracao", None),
                    "chunk_hash": getattr(x, "chunk_hash", None),
                }
                res.append(TrechoRecuperado(**data))
            else:
                res.append(x)
        return res


class ClassificacaoSentimento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    polaridade: Literal["positiva", "negativa", "neutra", "indeterminada"]
    justificativa: str
    necessidade_revisao: bool = False
    confianca_estimada: float = Field(ge=0.0, le=1.0)


class DecisaoOperador(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solicitacao_id: str
    decisao: Literal["pendente", "aprovada", "rejeitada", "revisar"]
    justificativa: str
    operador: str = "servidor_responsavel"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
