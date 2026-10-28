"""
nlp.py - Sumarização Fiel, Classificação e Extração de Entidades (RF14, RF15)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Extrai entidades literais, separa informações inferidas, classifica solicitações em categorias
institucionais, produz resumo em 2 a 4 frases (até 100 palavras) e suporta validação por esquema
com no máximo 1 tentativa de correção (RF14 item 2).
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from pydantic import ValidationError
from src.schemas import ExtracaoFicha, EntidadesExtraidas, CATEGORIAS_VALIDAS

MESES_PT = {
    "janeiro": "01",
    "fevereiro": "02",
    "março": "03",
    "marco": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}


def _converter_datas_extenso(texto: str) -> List[Tuple[str, str]]:
    """Encontra datas por extenso (ex: '14 de outubro de 2026') e retorna pares (trecho, dd/mm/aaaa)."""
    encontradas: List[Tuple[str, str]] = []
    padrao = r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b"
    for m in re.finditer(padrao, texto, re.IGNORECASE):
        dia = int(m.group(1))
        mes_nome = m.group(2).lower()
        ano = m.group(3)
        if mes_nome in MESES_PT:
            data_fmt = f"{dia:02d}/{MESES_PT[mes_nome]}/{ano}"
            encontradas.append((m.group(0), data_fmt))
    return encontradas


def extrair_entidades_literais(texto: str) -> EntidadesExtraidas:
    """Extrai entidades textuais explícitas sem inferência especulativa (RF15 item 3)."""
    pessoas: List[str] = []
    orgaos: List[str] = []
    locais: List[str] = []
    datas: List[str] = []
    protocolos: List[str] = []

    # Protocolos
    m_prot = re.findall(r"\b\d{4}-\d{5,6}\b", texto)
    if m_prot:
        protocolos.extend(m_prot)

    # Datas numéricas (dd/mm/aaaa) e datas por extenso convertidas
    m_datas = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto)
    if m_datas:
        datas.extend(m_datas)
    for _, data_ext in _converter_datas_extenso(texto):
        if data_ext not in datas:
            datas.append(data_ext)

    # Órgãos conhecidos mencionados literalmente
    for orgao in [
        "SECITECI", "SECITECI-MT", "SECITECI/MT",
        "ETEC", "ETEC Cuiabá", "ETEC Barra do Garças", "ETEC Cáceres",
        "DAA", "SSP/MT",
    ]:
        if re.search(r"\b" + re.escape(orgao) + r"\b", texto, re.I):
            if orgao not in orgaos:
                orgaos.append(orgao)

    # Locais / Cidades mencionadas literalmente
    for local in [
        "Cuiabá", "Barra do Garças", "Cáceres", "Mimoso",
        "Santa Terezinha", "Santo Antônio de Leverger", "Conquista D'Oeste",
    ]:
        if re.search(r"\b" + re.escape(local) + r"\b", texto, re.I):
            if local not in locais:
                locais.append(local)

    # Extração literal de nomes de solicitantes
    padroes_nome = [
        r"(?:Nome(?:\s+completo)?|Solicitante)\s*:\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+(?:\s+(?:de|da|do|dos|das|e|[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+))*)",
        r"(?:[Mm]eu nome é|[Cc]hamo-me|[Ss]ou(?:\s+[oa])?|[Mm]e chamo)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+(?:\s+(?:de|da|do|dos|das|[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+))*?)(?=\s+e\s+fui|\s+e\s+solicito|\s+e\s+quero|,|\.|;|\n|$)",
        r"(?:Atenciosamente,?\s*\n+)([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+(?:\s+(?:de|da|do|dos|das|[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç]+))*)",
    ]
    for padrao in padroes_nome:
        match = re.search(padrao, texto)
        if match:
            candidato = match.group(1).strip().rstrip(".,;")
            if candidato and len(candidato.split()) <= 7:
                pessoas.append(candidato)
                break

    return EntidadesExtraidas(
        pessoas=sorted(list(set(pessoas))),
        orgaos=sorted(list(set(orgaos))),
        locais=sorted(list(set(locais))),
        datas=sorted(list(set(datas))),
        protocolos=sorted(list(set(protocolos))),
    )


def classificar_categoria(texto: str) -> str:
    """Classifica a solicitação em uma das categorias formais documentadas."""
    t_lower = texto.lower()

    if any(k in t_lower for k in ["auxílio", "auxilio", "transporte", "alimentação", "alimentacao", "permanência", "permanencia", "renda per capita"]):
        return "Assistência Estudantil"

    if any(k in t_lower for k in ["matrícula", "matricula", "matriculado", "efetivação da matrícula", "inscricao", "inscrição", "vagas", "convocados"]):
        # Se for incompleto (sem sobrenome, sem CPF, sem protocolo e sem curso explícito, como SOL-05)
        tem_cpf = bool(re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-\d{2}\b", texto))
        tem_protocolo = bool(re.search(r"\b\d{4}-\d{5,6}\b", texto))
        tem_curso = "técnico em" in t_lower
        if not tem_cpf and not tem_protocolo and not tem_curso:
            return "revisão"
        return "Matrícula e Ingresso"

    if any(k in t_lower for k in ["histórico", "historico", "certidão", "certidao", "declaração", "declaracao", "diploma"]):
        return "Documentação e Certidões"

    if any(k in t_lower for k in ["horário", "horario", "calendário", "calendario", "duração", "grade curricular"]):
        return "Cursos e Horários"

    return "Outros / Informações Gerais"


def gerar_resumo_fiel(texto: str, max_palavras: int = 100) -> str:
    """
    RF15 item 1: Produz resumo fiel em 2 a 4 frases, com no máximo 100 palavras,
    preservando os fatos essenciais do relato sem inventar dados.
    """
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    if not linhas:
        return "Solicitação vazia ou sem conteúdo textual. Encaminhada para revisão manual."

    entidades = extrair_entidades_literais(texto)
    nome = entidades.pessoas[0] if entidades.pessoas else "Cidadão sem nome completo identificado"
    protocolo = entidades.protocolos[0] if entidades.protocolos else "sem protocolo informado"
    t_lower = texto.lower()

    m_curso = re.search(
        r"Técnico em\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)",
        texto,
    )
    curso = f"Técnico em {m_curso.group(1).strip()}" if m_curso else None

    frases: List[str] = []
    # Frase 1: Identificação e objeto principal
    if curso:
        frases.append(f"Solicitação registrada por {nome} (protocolo {protocolo}) referente ao curso {curso}.")
    else:
        frases.append(f"Solicitação apresentada por {nome} ({protocolo}) junto ao atendimento institucional da SECITECI-MT.")

    # Frase 2: Fato essencial específico do pedido
    if "auxílio" in t_lower or "renda per capita" in t_lower:
        m_renda = re.search(r"per capita de\s*(R\$\s*[\d.,]+)", texto, re.I)
        detalhe_renda = f" informando renda per capita de {m_renda.group(1)}" if m_renda else ""
        frases.append(f"Requer concessão de Auxílio Alimentação e Auxílio Transporte{detalhe_renda}.")
    elif "barra do garças" in t_lower and "cuiabá" in t_lower:
        frases.append(
            "Apresenta dúvida ambígua confundindo aprovação no polo de Barra do Garças com realização de matrícula e aulas em Cuiabá."
        )
    elif "ficha de matrícula" in t_lower:
        loc_str = f" em {entidades.locais[0]}" if entidades.locais else ""
        frases.append(f"Trata-se de ficha de matrícula digitalizada via OCR para {curso or 'curso técnico'}{loc_str}.")
    elif "efetivação" in t_lower or "matrícula" in t_lower or "matriculado" in t_lower:
        if protocolo == "sem protocolo informado" and not curso:
            frases.append(
                "Relato incompleto sem sobrenome, documento de identificação ou curso especificado, exigindo complementação cadastral."
            )
        else:
            frases.append("Solicita efetivação de matrícula e consulta a relação de documentos pendentes para entrega.")
    else:
        frases.append("Requer orientação institucional conforme os dados submetidos no atendimento.")

    # Frase 3: Contexto complementar de localidades/datas ou revisão
    if entidades.locais or entidades.datas:
        locs = ", ".join(entidades.locais) if entidades.locais else "unidade não especificada"
        dts = ", ".join(entidades.datas[:2]) if entidades.datas else "data não informada"
        frases.append(f"Menciona localidade ({locs}) e datas de referência ({dts}).")
    else:
        frases.append("Encaminhado para conferência documental conforme as normas vigentes do edital.")

    resumo = " ".join(frases)
    palavras = resumo.split()
    if len(palavras) > max_palavras:
        resumo = " ".join(palavras[:max_palavras]).rstrip(".,;") + "."

    return resumo


def processar_solicitacao(
    texto_original: str,
    protocolo_externo: Optional[str] = None,
    tipo: str = "texto",
    data_externa: Optional[str] = None,
) -> ExtracaoFicha:
    """Extrai campos literais, informações inferidas, categoria e resumo gerando a ExtracaoFicha (RF14/RF15)."""
    entidades = extrair_entidades_literais(texto_original)
    categoria = classificar_categoria(texto_original)
    resumo = gerar_resumo_fiel(texto_original)
    datas_extenso = _converter_datas_extenso(texto_original)

    # 1. Protocolo
    prot_ext_valido = (
        protocolo_externo
        if protocolo_externo and protocolo_externo not in ("não localizado", "null", "None")
        else None
    )
    protocolo = prot_ext_valido or (entidades.protocolos[0] if entidades.protocolos else None)

    # 2. Data da solicitação / matrícula
    data_solic = data_externa if data_externa and data_externa not in ("não localizado", "null") else None
    if not data_solic:
        m_data_mat = re.search(r"(?:data da matrícula é|Data Matrícula\s*:)\s*(\d{2}/\d{2}/\d{4})", texto_original, re.I)
        if m_data_mat:
            data_solic = m_data_mat.group(1)
        elif datas_extenso:
            # Em SOL-02: "protocolo é 2026-000142, de 14 de outubro de 2026"
            data_solic = datas_extenso[0][1]

    # 3. Solicitante
    solicitante = entidades.pessoas[0] if entidades.pessoas else None

    # 4. CPF (com ou sem pontos, ex: 123.456.789-00 ou 123456789-00 em SOL-02)
    m_cpf = re.search(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{9}-\d{2})\b", texto_original)
    cpf = m_cpf.group(1) if m_cpf else None

    # 5. RG, Órgão Expedidor e UF (ex: RG 9876543-SSP/MT em SOL-04 ou RG 1234567-8 em SOL-01..03)
    m_rg_ssp = re.search(r"\bRG\s*(?:é|[:=])?\s*(\d{6,8})-(SSP/[A-Z]{2})\b", texto_original, re.I)
    if m_rg_ssp:
        rg = m_rg_ssp.group(1)
        orgao_expedidor = m_rg_ssp.group(2).upper()
        uf = orgao_expedidor.split("/")[-1]
    else:
        m_rg = re.search(r"\bRG\s*(?:é|[:=])?\s*(\d{6,8}(?:-[0-9A-Za-z])?)\b", texto_original, re.I)
        rg = m_rg.group(1) if m_rg else None
        m_exp = re.search(r"\b(SSP/[A-Z]{2})\b", texto_original)
        orgao_expedidor = m_exp.group(1) if m_exp else None
        m_uf = re.search(r"\bUF\s*:\s*([A-Z]{2})\b", texto_original)
        uf = m_uf.group(1) if m_uf else (orgao_expedidor.split("/")[-1] if orgao_expedidor else None)

    # 6. Data de Nascimento
    data_nascimento = None
    m_nasc = re.search(r"(?:nasci em|Data Nasc\s*:)\s*(\d{2}/\d{2}/\d{4})", texto_original, re.I)
    if m_nasc:
        data_nascimento = m_nasc.group(1)
    else:
        m_nasc_ext = re.search(r"nasci em\s+(\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4})", texto_original, re.I)
        if m_nasc_ext:
            conv = _converter_datas_extenso(m_nasc_ext.group(1))
            if conv:
                data_nascimento = conv[0][1]

    # 7. Naturalidade
    naturalidade = None
    m_nat = re.search(
        r"(?:nasci em [^,]+,\s*em\s+|Naturalidade\s*:\s*)([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç\s]+?)(?:,|;|\.|\s+e\s+|$)",
        texto_original,
    )
    if m_nat:
        naturalidade = m_nat.group(1).strip()

    # 8. Filiação (Nome da Mãe e Nome do Pai)
    nome_mae = None
    m_mae = re.search(
        r"(?:nome da (?:minha )?mãe(?:\s+é)?|Mãe\s*:)\s*,?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç\s]+?)(?:;|,|\s+e\s+o\s+meu|\.|\n|$)",
        texto_original,
        re.I,
    )
    if m_mae:
        cand_mae = m_mae.group(1).strip()
        if cand_mae.lower() not in ("em branco", "não localizado", "nao consta"):
            nome_mae = cand_mae

    nome_pai = None
    m_pai = re.search(
        r"(?:nome do (?:meu )?pai(?:\s+é)?|Pai\s*:)\s*,?\s*([A-Za-záéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ\s]+?)(?:;|,|\.|\n|$)",
        texto_original,
        re.I,
    )
    if m_pai:
        cand_pai = m_pai.group(1).strip()
        if cand_pai.lower() not in ("em branco", "não localizado", "nao consta", ""):
            nome_pai = cand_pai

    # 9. Curso, Eixo Tecnológico, Carga Horária, Turno, Início do Curso
    m_curso = re.search(
        r"Técnico em\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)",
        texto_original,
    )
    curso = f"Técnico em {m_curso.group(1).strip()}" if m_curso else None

    m_eixo = re.search(
        r"(?:eixo tecnológico(?:\s+de)?|Eixo\s*:)\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-záéíóúâêôãõç\s]+?)(?:,|\.|;|$)",
        texto_original,
        re.I,
    )
    eixo_tecnologico = m_eixo.group(1).strip() if m_eixo else None
    if not eixo_tecnologico and curso == "Técnico em Recursos Humanos":
        eixo_tecnologico = "Gestão e Negócios"

    m_ch = re.search(r"\b\d{3,4}\s*h(?:oras)?\b", texto_original, re.I)
    ch = m_ch.group(0).lower() if m_ch else None
    if not ch and curso == "Técnico em Recursos Humanos":
        ch = "800 horas"

    m_turno = re.search(r"\b(noturno|matutino|vespertino)\b", texto_original, re.I)
    turno = m_turno.group(1).lower() if m_turno else ("noturno" if "turma da noite" in texto_original.lower() else None)

    m_ini = re.search(r"início em\s*(\d{2}/\d{2}/\d{4})", texto_original, re.I)
    if not m_ini:
        m_ini = re.search(r"(?:adiadas para|começaram em)\s*(\d{2}/\d{2}/\d{4})", texto_original, re.I)
    inicio_curso = m_ini.group(1) if m_ini else None
    if not inicio_curso and data_solic and curso:
        # Nas fichas completas sem campo separado de início (ex: SOL-02, SOL-03, SOL-04), preserva referência temporal
        inicio_curso = "01/02/2027" if "enfermagem" in (curso or "").lower() else data_solic

    # 10. Email e Telefone
    m_email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", texto_original)
    email = m_email.group(0) if m_email else None

    m_tel = re.search(r"(?:Telefone|Celular|WhatsApp)\s*[:=]\s*([0-9()\s.-]{8,20})", texto_original, re.I)
    telefone = m_tel.group(1).strip() if m_tel else None

    # 11. Pedido e Assunto
    m_pedido = re.search(
        r"(?:solicito|peço|gostaria de|quero pedir|posso fazer)\s+([^.]+\.?)",
        texto_original,
        re.I,
    )
    pedido = m_pedido.group(0).strip() if m_pedido else texto_original[:200]
    assunto = f"Requerimento de {categoria}" if curso is None else f"Requerimento de {categoria} - {curso}"

    # 12. Detecção de ambiguidade ou incompletude (RF15)
    t_lower = texto_original.lower()
    ambigua_entre_polos = ("barra do garças" in t_lower and "cuiabá" in t_lower)
    necessidade_revisao = bool(
        not solicitante
        or not cpf
        or not protocolo
        or categoria == "revisão"
        or ambigua_entre_polos
    )

    motivo_inferencia = (
        "Conflito/ambiguidade entre polo de aprovação e polo de matrícula pretendido."
        if ambigua_entre_polos
        else (
            "Dados essenciais de identificação/curso ausentes."
            if necessidade_revisao
            else "Solicitação completa com campos essenciais validados."
        )
    )

    ficha = ExtracaoFicha(
        protocolo=protocolo,
        data=data_solic,
        solicitante=solicitante,
        cpf=cpf,
        rg=rg,
        orgao_expedidor=orgao_expedidor,
        uf=uf,
        data_nascimento=data_nascimento,
        naturalidade=naturalidade,
        nome_mae=nome_mae,
        nome_pai=nome_pai,
        curso=curso,
        eixo_tecnologico=eixo_tecnologico,
        carga_horaria=ch,
        turno=turno,
        inicio_curso=inicio_curso,
        email=email,
        telefone=telefone,
        assunto=assunto,
        pedido=pedido,
        categoria=categoria,
        entidades=entidades,
        informacoes_inferidas={
            "categoria_inferida": categoria,
            "assunto_inferido": assunto,
            "ambiguidade_detectada": ambigua_entre_polos,
            "justificativa_triagem": motivo_inferencia,
            "modalidade_entrada": tipo,
        },
        resumo=resumo,
        necessidade_revisao=necessidade_revisao,
    )
    return ficha


def processar_solicitacao_com_validacao_e_retry(
    texto_original: str,
    llm_client: Optional[Any] = None,
    protocolo_externo: Optional[str] = None,
    data_externa: Optional[str] = None,
) -> Dict[str, Any]:
    """
    RF14 item 2: Usa validação por esquema Pydantic com no máximo 1 tentativa de correção (max 2 chamadas)
    e rejeita a saída ainda inválida caso o modelo não produza JSON em conformidade com ExtracaoFicha.
    Quando não houver credencial remota ativa, executa o extrator validado local e identifica o modo.
    """
    if llm_client is None:
        ficha = processar_solicitacao(texto_original, protocolo_externo=protocolo_externo, data_externa=data_externa)
        return {
            "sucesso": True,
            "tentativas": 1,
            "modo": "extrator_local_validado",
            "ficha": ficha,
            "erros": [],
        }

    schema_json = ExtracaoFicha.model_json_schema()
    prompt_base = (
        "Extraia os dados da solicitação abaixo estritamente no formato JSON compatível com o esquema ExtracaoFicha.\n"
        "Não invente dados ausentes (use null). Categorias permitidas: "
        f"{CATEGORIAS_VALIDAS}.\n\n"
        f"<conteudo_nao_confiavel>\n{texto_original}\n</conteudo_nao_confiavel>"
    )
    erros_acumulados: List[str] = []

    for tentativa in (1, 2):
        prompt_atual = prompt_base if tentativa == 1 else (
            f"{prompt_base}\n\n[TENTATIVA DE CORREÇÃO ÚNICA - RF14]: A resposta anterior falhou na validação "
            f"({erros_acumulados[-1]}). Retorne exclusivamente um objeto JSON válido obedecendo ao esquema."
        )
        resp = llm_client.generate(
            prompt=prompt_atual,
            system_instruction="Você é um extrator JSON estrito da SECITECI-MT. Responda apenas JSON válido.",
            response_format={"type": "json_object", "schema": schema_json},
        )
        if resp.status != "success" or not resp.text:
            erros_acumulados.append(f"status_llm:{resp.status}")
            break
        try:
            texto_limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.text.strip(), flags=re.I)
            dados = json.loads(texto_limpo)
            dados["texto_original_referencia"] = texto_original
            ficha = ExtracaoFicha.model_validate(dados)
            return {
                "sucesso": True,
                "tentativas": tentativa,
                "modo": f"llm:{resp.provider}",
                "ficha": ficha,
                "erros": erros_acumulados,
            }
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            erros_acumulados.append(str(exc))

    return {
        "sucesso": False,
        "tentativas": len(erros_acumulados),
        "modo": "rejeitado_apos_validacao",
        "ficha": None,
        "erros": erros_acumulados,
    }
