"""Política de segurança executável sem servidor ou dependências web."""
import pytest
from src.audit import AuditLogger
from src import resolver_caminho
from src.image_access import (ImageAccessError, exigir_revisor_imagem,
                              identidade_revisor, imagem_publicavel)
from testes.test_image_rf10 import geracao


def test_autenticacao_ausente_falha_fechada():
    with pytest.raises(ImageAccessError) as exc:
        exigir_revisor_imagem()
    assert exc.value.status_code == 503


@pytest.mark.parametrize('principal,codigo', [(None, 401), ({'operador': 'forjado'}, 401),
    ({'sub': 'revisor', 'permissoes': []}, 403)])
def test_identidade_e_permissao_obrigatorias(principal, codigo):
    with pytest.raises(ImageAccessError) as exc:
        identidade_revisor(principal)
    assert exc.value.status_code == codigo


@pytest.mark.parametrize('caso', ['pendente', 'rejeitada', 'alterada', 'sem_autenticacao', 'revogada', 'aprovada'])
def test_publicacao_por_estado_e_hash_atual(geracao, caso):
    gerador, _, _, tmp = geracao
    gerado = gerador.gerar_comunicado_oficial()
    logger = AuditLogger(str(tmp / 'logs'))
    identificador = gerado['id_execucao']
    sha = gerado['metadados']['sha256_imagem']
    imagem = resolver_caminho(gerado['caminho_imagem'])
    sujeito = identidade_revisor({'sub': 'revisor-autenticado', 'permissoes': ['rf10:revisar']})
    if caso != 'pendente':
        resultado = gerador.revisar_imagem(identificador, sha,
            'REJEITADO' if caso == 'rejeitada' else 'APROVADO', 'Conferencia teste', sujeito, logger,
            identidade_autenticada=None if caso == 'sem_autenticacao' else sujeito)
        assert resultado['sucesso']
    if caso == 'alterada':
        imagem.write_bytes(imagem.read_bytes() + b'adulterado')
    if caso == 'revogada':
        assert gerador.revisar_imagem(identificador, sha, 'REJEITADO', 'Revisao posterior', sujeito, logger,
                                     identidade_autenticada=sujeito)['sucesso']
    if caso == 'aprovada':
        dados, nome = imagem_publicavel(gerador, logger, identificador)
        assert dados == imagem.read_bytes() and nome == imagem.name
    else:
        with pytest.raises(ImageAccessError) as exc:
            imagem_publicavel(gerador, logger, identificador)
        assert exc.value.status_code == 403
