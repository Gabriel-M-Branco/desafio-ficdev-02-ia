"""
nlp.py - Sumarização Fiel, Classificação e Extração de Entidades (RF15)
Central Inteligente de Atendimento - GOV.MT / SECITECI-MT
Extrai entidades literais, classifica solicitações em categorias institucionais
e produz resumo de até 100 palavras preservando fatos essenciais sem alucinações.
"""

import re
from typing import Dict, Any, List, Optional
from src.schemas import ExtracaoFicha, EntidadesExtraidas, CATEGORIAS_VALIDAS


def extrair_entidades_literais(texto: str) -> EntidadesExtraidas:
    """Extrai entidades textuais explícitas sem inferência especulativa."""
    pessoas = []
    orgaos = []
    locais = []
    datas = []
    protocolos = []

    # Protocolos
    m_prot = re.findall(r"\b\d{4}-\d{5,6}\b", texto)
    if m_prot:
        protocolos.extend(m_prot)

    # Datas (dd/mm/aaaa)
    m_datas = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto)
    if m_datas:
        datas.extend(m_datas)

    # Órgãos conhecidos
    for orgao in ["SECITECI", "SECITECI-MT", "SECITECI/MT", "ETEC", "ETEC Cuiabá", "ETEC Barra do Garças", "ETEC Cáceres", "DAA"]:
        if re.search(r"\b" + re.escape(orgao) + r"\b", texto, re.I):
            if orgao not in orgaos:
                orgaos.append(orgao)

    # Locais / Cidades
    for local in ["Cuiabá", "Barra do Garças", "Cáceres", "Mimoso", "Santa Terezinha", "Santo Antônio de Leverger", "Conquista D'Oeste"]:
        if re.search(r"\b" + re.escape(local) + r"\b", texto, re.I):
            if local not in locais:
                locais.append(local)

    # Extração genérica de nomes de solicitantes por padrões de redação
    padroes_nome = [
        r"(?i)(?:meu nome é|chamo-me|sou|me chamo)(?:\s+[oa])?\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)",
        r"(?i)(?:Nome(?:\s+completo)?|Solicitante):\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)",
        r"(?i)(?:Atenciosamente,?\s*\n+)([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)"
    ]
    for padrao in padroes_nome:
        match = re.search(padrao, texto)
        if match:
            candidato = match.group(1).strip()
            if candidato and len(candidato.split()) <= 6:
                pessoas.append(candidato)
                break

    return EntidadesExtraidas(
        pessoas=sorted(list(set(pessoas))),
        orgaos=sorted(list(set(orgaos))),
        locais=sorted(list(set(locais))),
        datas=sorted(list(set(datas))),
        protocolos=sorted(list(set(protocolos)))
    )


def classificar_categoria(texto: str) -> str:
    """Classifica a solicitação em uma das categorias formais documentadas."""
    t_lower = texto.lower()

    if any(k in t_lower for k in ["auxílio", "auxilio", "transporte", "alimentação", "alimentacao", "permanência", "permanencia", "renda per capita"]):
        return "Assistência Estudantil"

    if any(k in t_lower for k in ["matrícula", "matricula", "efetivação da matrícula", "inscricao", "inscrição", "vagas"]):
        # Se for muito incompleto ou confuso
        if len(texto.split()) < 20 and not any(k in t_lower for k in ["cpf", "protocolo"]):
            return "revisão"
        return "Matrícula e Ingresso"

    if any(k in t_lower for k in ["histórico", "historico", "certidão", "certidao", "declaração", "declaracao", "diploma"]):
        return "Documentação e Certidões"

    if any(k in t_lower for k in ["horário", "horario", "calendário", "calendario", "duração", "grade curricular"]):
        return "Cursos e Horários"

    return "Outros / Informações Gerais"


def gerar_resumo_fiel(texto: str, max_palavras: int = 100) -> str:
    """Produz resumo conciso de até 100 palavras sem inventar dados."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    if not linhas:
        return "Solicitação vazia ou sem conteúdo."

    # Identifica solicitante e pedido essencial
    entidades = extrair_entidades_literais(texto)
    nome = entidades.pessoas[0] if entidades.pessoas else "Cidadão não identificado"
    protocolo = entidades.protocolos[0] if entidades.protocolos else "Protocolo ausente"
    
    # Extrai trecho do pedido
    pedido_match = re.search(r"(?:solicito|peço|gostaria de|quero)\s+([^.]+)", texto, re.I)
    detalhe_pedido = pedido_match.group(0).strip() if pedido_match else "solicita informações institucionais"

    resumo = f"Manifestação de {nome} ({protocolo}), que {detalhe_pedido}."
    
    # Garante limite estrito de palavras
    palavras = resumo.split()
    if len(palavras) > max_palavras:
        resumo = " ".join(palavras[:max_palavras]) + "..."
        
    return resumo


def processar_solicitacao(
    texto_original: str,
    protocolo_externo: Optional[str] = None,
    tipo: str = "texto"
) -> ExtracaoFicha:
    """Extrai campos, entidades, categoria e resumo gerando a ExtracaoFicha (RF14/RF15)."""
    entidades = extrair_entidades_literais(texto_original)
    categoria = classificar_categoria(texto_original)
    resumo = gerar_resumo_fiel(texto_original)

    # Protocolo
    protocolo = protocolo_externo or (entidades.protocolos[0] if entidades.protocolos else None)

    # Solicitante
    solicitante = entidades.pessoas[0] if entidades.pessoas else None

    # CPF e RG
    m_cpf = re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", texto_original)
    cpf = m_cpf.group(0) if m_cpf else None

    m_rg = re.search(r"\b\d{6,8}-?[A-Za-z0-9]?\b", texto_original)
    rg = m_rg.group(0) if m_rg else None

    # Curso
    m_curso = re.search(r"Técnico em\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)", texto_original)
    curso = f"Técnico em {m_curso.group(1).strip()}" if m_curso else None

    # Turno
    m_turno = re.search(r"\b(noturno|matutino|vespertino)\b", texto_original, re.I)
    turno = m_turno.group(1).lower() if m_turno else None

    # Carga horária
    m_ch = re.search(r"\b\d{3,4}\s*h(?:oras)?\b", texto_original, re.I)
    ch = m_ch.group(0).lower() if m_ch else None

    # Email
    m_email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", texto_original)
    email = m_email.group(0) if m_email else None

    # Pedido
    m_pedido = re.search(r"(?:solicito|peço|gostaria de|quero)\s+([^.]+\.?)", texto_original, re.I)
    pedido = m_pedido.group(0).strip() if m_pedido else texto_original[:200]

    # Assunto
    assunto = f"Requerimento de {categoria}" if curso is None else f"Requerimento de {categoria} - {curso}"

    # Regra de negócio: se for incompleto (como SOL-05), marca necessidade_revisao
    necessidade_revisao = False
    if not solicitante or not cpf or not protocolo or categoria == "revisão":
        necessidade_revisao = True

    ficha = ExtracaoFicha(
        protocolo=protocolo,
        solicitante=solicitante,
        cpf=cpf,
        rg=rg,
        curso=curso,
        turno=turno,
        carga_horaria=ch,
        email=email,
        assunto=assunto,
        pedido=pedido,
        categoria=categoria,
        entidades=entidades,
        resumo=resumo,
        necessidade_revisao=necessidade_revisao
    )
    return ficha
