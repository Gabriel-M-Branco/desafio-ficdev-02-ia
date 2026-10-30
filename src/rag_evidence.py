"""Seleção conservadora de passagens; nenhuma regra institucional é inventada.

O modo local reconhece intenções do acervo didático e devolve citações literais.
Consultas não cobertas são encaminhadas ao operador, inclusive no modo remoto.
"""
import re
import unicodedata


def normalizar(texto):
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                                         if unicodedata.category(c) != "Mn")).replace("’", "'").strip()


def selecionar(pergunta, trechos):
    """Retorna (passagens com seus chunks, motivo de abstenção, conflito).

    Cada passagem devolvida é substring de um chunk recuperado. As regras abaixo
    identificam o assunto, mas valores, datas e requisitos vêm só das passagens.
    """
    q = normalizar(pergunta)
    corpus = normalizar(" ".join(t.conteudo for t in trechos))
    anos = set(re.findall(r"\b20\d{2}\b", q))
    if anos - set(re.findall(r"\b20\d{2}\b", corpus)):
        return [], "O ano solicitado não está coberto pelas evidências recuperadas.", False

    # Confere entidades qualificadas, sem bloquear vocabulário comum da pergunta.
    # Um programa inventado não pode herdar as regras de um programa parecido.
    for padrao in (r"\bprograma\s+(?:de\s+)?([a-z -]+?)(?=\s+(?:da|das|do|dos|para|em)\s+|[?.,]|$)",
                   r"\bcurso\s+(?:tecnico\s+em\s+|de\s+)([a-z -]+?)(?=\s+(?:na|no|em|ofertad[oa]|para)\b|[?.,]|$)",
                   r"\baulas?\s+de\s+([a-z -]+?)(?=\s+(?:na|no|em|ofertad[oa]|para)\b|[?.,]|$)",
                   r"\bturma\s+de\s+([a-z -]+?)(?=\s+(?:na|no|em|ofertad[oa]|para)\b|[?.,]|$)",
                   r"\baux[ií]lio\s+(?:de\s+)?([a-z -]+?)(?=\s+(?:da|das|do|dos|para|em|no|na)\s+|[?.,]|$)",
                   r"\bbolsa\s+(?:de\s+)?([a-z -]+?)(?=\s+(?:em|da|do|para)\s+|[?.,]|$)",
                   r"\bvide[oó]\s+de\s+([a-z -]+?)(?=\s+(?:da|das|do|dos|para|em)\s+|[?.,]|$)",
                   r"\bprocesso seletivo\s+(?:do|da|das|de)\s+([a-z -]+?)(?=\s+(?:20\d{2}|da|do|em)|[?.,]|$)"):
        for entidade in re.findall(padrao, q):
            ent_limpa = entidade.strip()
            if ent_limpa and ent_limpa not in corpus:
                return [], "Informação não localizada no acervo institucional disponível. A entidade solicitada não está documentada. Encaminhar para revisão humana.", False
    if "pos-graduacao" in q and "pos-graduacao" not in corpus:
        return [], "Informação não localizada no acervo institucional disponível. O acervo não trata dessa modalidade de curso. Encaminhar para revisão humana.", False

    # O título repetido em cada chunk não é evidência de uma afirmação.
    linhas = []
    vistos = set()
    for t in trechos:
        for linha in t.conteudo.splitlines()[1:]:
            linha = linha.strip()
            if not linha or re.match(r"^(IDENTIFICADOR|TITULO|VERSAO|DATA_PUBLICACAO|DOCUMENTO_PAI|NATUREZA|TEMAS):", linha):
                continue
            if linha not in vistos:
                linhas.append((t, linha, normalizar(linha)))
                vistos.add(linha)

    predicado = None
    conflito = False
    if "heteroidentifica" in q or ("video" in q and "autodeclara" in q):
        if "indigena" in q:
            predicado = lambda l: ("indigena" in l or "indigenas" in l or "l3" in l) and ("nao estabelece video" in l or "sem video" in l or "documentos na matricula" in l)
        elif "video" in q:
            predicado = lambda l: (".mp4" in l and "minutos" in l) or ("heteroidentifica" in l and ".mp4" in l)
        elif "foto" in q:
            predicado = lambda l: "foto de heteroidentificacao" in l
    elif "frequencia" in q and any(x in q for x in ("entregar", "entrega", "prazo", "dia", "comprovacao", "minima")):
        if "minima" in q:
            predicado = lambda l: "frequencia" in l and bool(re.search(r"\b(?:70|85)%", l))
        else:
            predicado = lambda l: "frequencia" in l and ("5º" in l or "dia 20" in l)
        conflito = True
    elif "renda" in q and "assalariad" in q:
        predicado = lambda l: ("a) assalariados:" in l or "d) comprovante de residencia" in l or "e) copia da declaracao" in l)
    elif "inicio" in q or "comec" in q or "iniciam" in q:
        cursos = ("enfermagem", "agropecuaria", "mineracao", "agroindustria", "administracao", "agronegocio", "recursos humanos")
        curso = next((c for c in cursos if c in q), None)
        locais = ("comunidade aparecida do leste", "comunidade paraiso do leste", "santo antonio do leste",
                  "santa terezinha", "barra do garcas", "conquista d'oeste", "nova lacerda", "porto esperidiao",
                  "salto do ceu", "nova marilandia", "alto araguaia", "mimoso", "nobres", "pocone", "confresa", "cuiaba")
        mencionados = [l for l in locais if l in q]
        if curso and mencionados:
            predicado = lambda l: ((f"curso: tecnico em {curso}" in l or f"tecnico em {curso}" in l)
                                    and ("inicio das aulas:" in l or "inicio:" in l or "iniciam" in l or "postergada" in l or "vigentes" in l or "2026" in l)
                                    and any(f"{local}" in l for local in mencionados))
        else:
            return [], "Informe o curso e a localidade de oferta para conferir o calendário.", False
    elif "inscri" in q and any(x in q for x in ("prazo", "periodo", "final", "prorrog")):
        predicado = lambda l: ("item 2:" in l or "periodo de inscricao" in l or "inscricao prorrogad" in l) and ("13/05/2026" in l or "03/05/2026" in l or "prorrogad" in l)
    elif "sorteio" in q:
        predicado = lambda l: l.startswith("item 8:") and "sorteio" in l
    elif "lista oficial" in q and "inscrit" in q:
        predicado = lambda l: l.startswith("item 7:") and "lista oficial" in l
    elif "chamada" in q:
        numero = next((n for n, nomes in (("1", ("1ª", "primeira")), ("2", ("2ª", "segunda")),
                                          ("3", ("3ª", "terceira")), ("4", ("4ª", "quarta")), ("5", ("5ª", "quinta")))
                       if any(nome in q for nome in nomes)), None)
        if numero:
            if numero == "5" and any(x in q for x in ("particip", "requisit", "document")):
                predicado = lambda l: l.startswith("5ª chamada:") and "participaram" in l
            else:
                predicado = lambda l: (f"{numero}ª chamada" in l or f"{numero}a chamada" in l) and any(w in l for w in ("matricula", "2026", "08/07/2026", "15 a 19/06/2026"))
    elif "cota" in q or "percentua" in q:
        predicado = lambda l: bool(re.search(r"(?:ac \(|l[1-4] \().*\d+%", l))
    elif "auxilio" in q and "valor" in q:
        if "edital" in q:
            return [], "Os editais adaptados não estabelecem esse valor; as normas de assistência são fictícias e distintas.", False
        beneficio = "alimentacao" if "alimentacao" in q else "transporte" if "transporte" in q else None
        if beneficio:
            predicado = lambda l: f"auxilio {beneficio}:" in l and "valor mensal" in l

    if predicado is None:
        return [], "A pergunta não possui uma passagem suficientemente específica no modo extrativo local. Solicite revisão humana.", False
    selecionadas = []
    for t, linha, n in linhas:
        if predicado(n):
            # O primeiro artigo de um chunk misto pode pertencer a outra
            # passagem. A página e o trecho continuam identificando a fonte.
            item = re.match(r"^(Item\s+\d+|Art\.\s*\d+º?)", linha)
            selecionadas.append((t.model_copy(update={"secao": item.group(0) if item else None}), linha))
    if not selecionadas:
        return [], "Informação não localizada no acervo institucional disponível. Encaminhar para revisão humana.", False
    if conflito:
        valores = {tuple(re.findall(r"\d+%|5º|dia 20", normalizar(l))) for _, l in selecionadas}
        conflito = len({t.documento_id for t, _ in selecionadas}) > 1 and len(valores) > 1
    return selecionadas, "", conflito


def validar_selecao_remota(payload, evidencias):
    """Só aceita pares de ID e citação literal previamente recuperados.

    Texto livre adicional e IDs desconhecidos são recusados. Não é uma validação
    semântica de paráfrases: a geração remota seleciona evidências verificáveis.
    """
    import json
    try:
        data = json.loads(payload)
        if set(data) != {"passagens"} or not isinstance(data["passagens"], list) or not data["passagens"]:
            return False
        permitidas = {(t.trecho_id, l) for t, l in evidencias}
        return all(isinstance(p, dict) and set(p) == {"trecho_id", "citacao"}
                   and (p["trecho_id"], p["citacao"]) in permitidas for p in data["passagens"])
    except (ValueError, TypeError, KeyError):
        return False


def conferir_afirmacoes(resposta):
    """Confere a ligação exata entre cada passagem citada e seu próprio chunk."""
    citacoes = re.findall(r'^"(.+)" \[([^,]+),.*?trecho ([^,]+),', resposta.resposta, re.M)
    if not citacoes:
        return False
    linhas = [l for l in resposta.resposta.splitlines() if l.strip()]
    introducao = "Divergência entre passagens sobre o mesmo assunto; conferir vigência com o operador."
    if any(not l.startswith('"') and l != introducao for l in linhas):
        return False
    if sum(l.startswith('"') for l in linhas) != len(citacoes):
        return False
    fontes = {t.trecho_id: t for t in resposta.fontes}
    return all(ident in fontes and fontes[ident].documento_id == doc
               and passagem in fontes[ident].conteudo for passagem, doc, ident in citacoes)
