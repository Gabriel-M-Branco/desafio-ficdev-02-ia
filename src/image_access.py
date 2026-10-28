"""RF10: fronteira de integração com autenticação e publicação por hash."""
import hashlib
import json
import re

from src import resolver_caminho


class ImageAccessError(RuntimeError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def exigir_revisor_imagem():
    """Substituir por dependência do grupo que valide sessão e permissão RF10.

    Não lê identidade de headers/formulários e não cria autenticação paralela.
    Testes podem usar app.dependency_overrides com principal controlado.
    """
    raise ImageAccessError(503, "Revisão administrativa RF10 desabilitada até integração da autenticação do grupo.")


def identidade_revisor(principal):
    if (not isinstance(principal, dict) or not isinstance(principal.get("sub"), str)
            or not principal["sub"].strip()):
        raise ImageAccessError(401, "Identidade autenticada obrigatória.")
    if "rf10:revisar" not in principal.get("permissoes", []):
        raise ImageAccessError(403, "Permissão de revisão RF10 obrigatória.")
    return principal["sub"].strip()


def carregar_imagem(gerador, logger, identificador):
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
            raise ValueError()
        registro = json.loads((logger.log_dir / f"{identificador}.json").read_text(encoding="utf-8"))
        meta = registro["detalhes_completos"]
        caminho = resolver_caminho(meta["arquivo_imagem"]).resolve()
        if (registro["modalidade"] != "imagem" or not meta.get("sucesso") or not meta.get("ia_gerada")
                or not caminho.is_relative_to(gerador.output_dir.resolve())):
            raise ValueError()
        return meta, caminho
    except (OSError, ValueError, KeyError, TypeError):
        raise ImageAccessError(404, "Imagem institucional não localizada.")


def imagem_publicavel(gerador, logger, identificador):
    """A última decisão da trilha prevalece; entrega os próprios bytes verificados."""
    meta, caminho = carregar_imagem(gerador, logger, identificador)
    try:
        ultima = None
        # Não ignore linhas corrompidas: uma rejeição ilegível não pode reativar
        # uma aprovação anterior. Ordem append-only da trilha, não do diretório.
        eventos = [json.loads(linha) for linha in logger.trail_file.read_text(encoding="utf-8").splitlines() if linha.strip()]
        for evento in eventos:
            if evento.get("modalidade") != "imagem_revisao":
                continue
            id_evento = evento.get("id_execucao", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", id_evento):
                raise ValueError()
            registro = json.loads((logger.log_dir / f"{id_evento}.json").read_text(encoding="utf-8"))
            if registro.get("decisao_humana") != evento.get("decisao_humana"):
                raise ValueError()
            detalhe = registro["detalhes_completos"]
            if resolver_caminho(detalhe["arquivo_imagem"]).resolve() == caminho:
                ultima = registro
        if ultima is None:
            raise ValueError()
        detalhe = ultima["detalhes_completos"]
        decisao = ultima["decisao_humana"]
        if (decisao.get("status") != "APROVADO" or not decisao.get("identidade_autenticada")
                or detalhe.get("estado_imagem") != "aprovada"
                or detalhe.get("status_revisao") != "aprovada"
                or decisao != detalhe.get("revisao_humana")):
            raise ValueError()
        dados = caminho.read_bytes()
        atual = hashlib.sha256(dados).hexdigest()
        if atual != decisao.get("hash_imagem") or atual != detalhe.get("sha256_imagem") or atual != meta.get("sha256_imagem"):
            raise ValueError()
        return dados, caminho.name
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ImageAccessError(403, "Imagem sem aprovação autenticada vigente ou arquivo alterado.")
