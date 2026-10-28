"""Executor local: mocks de identidade/provedor; nenhuma inferência real."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from testes import validar_rf10_local as local
from src.image_access import exigir_revisor_imagem, ImageAccessError
from src.web_files import arquivo_publico


@pytest.mark.parametrize("ativar,gerar", [(False, False), (True, False), (False, True)])
def test_desativado_sem_dupla_confirmacao(monkeypatch, ativar, gerar):
    identidade = Mock(side_effect=AssertionError("Não executar nada"))
    monkeypatch.setattr(local, "identidade_windows", identidade)
    with pytest.raises(RuntimeError):
        local.gerar_teste_local(ativar, gerar)
    identidade.assert_not_called()


def test_identidade_vem_do_windows(monkeypatch):
    processo = Mock(return_value=SimpleNamespace(stdout=b'"PC\\revisor","S-1-5-21-123-456-789-1001"\r\n'))
    monkeypatch.setattr(local.subprocess, "run", processo)
    identidade = local.identidade_windows()
    assert identidade["usuario"] == "PC\\revisor"
    assert identidade["sid"] == "S-1-5-21-123-456-789-1001"
    assert processo.call_args.args[0][1:] == ["/user", "/fo", "csv", "/nh"]


def test_geracao_isolada_pendente_sem_publicacao(tmp_path, monkeypatch):
    from src.image_generation import ImageGenerator
    from src.audit import AuditLogger
    identidade = {"usuario": "PC\\teste", "sid": "S-1-5-21-1001", "origem": "token_sessao_windows"}
    monkeypatch.setattr(local, "identidade_windows", lambda: identidade)
    monkeypatch.setattr(local, "resolver_caminho", lambda p: Path(p) if Path(p).is_absolute() else tmp_path / p)
    gerador = SimpleNamespace(image_provider="cloudflare")
    def gerar(**kw):
        imagem = gerador.output_dir / kw["nome_arquivo"]
        imagem.write_bytes(b"bytes-do-transporte-simulado")
        sha = hashlib.sha256(imagem.read_bytes()).hexdigest()
        meta = {"sha256_imagem": sha, "tempo_processamento_segundos": 0.1}
        arquivo_meta = imagem.with_suffix('.json')
        arquivo_meta.write_text(json.dumps(meta))
        id_exec = kw['audit_logger'].registrar_execucao(modalidade='imagem', arquivo_origem=str(imagem),
            provedor='mock', modelo='mock', versao_prompt='teste', parametros={}, resultado=meta, duracao_segundos=0.1)
        return {"sucesso": True, "caminho_imagem": str(imagem), "metadados": meta,
                "caminho_metadados": str(arquivo_meta), "id_execucao": id_exec}
    gerador.gerar_comunicado_oficial = Mock(side_effect=gerar)
    monkeypatch.setattr('src.image_generation.ImageGenerator', lambda: gerador)
    resultado = local.gerar_teste_local(True, True)
    assert resultado['sucesso'] and resultado['status'] == 'pendente_revisao'
    assert resultado['publicacao_permitida'] is False
    assert resultado['identidade_local'] == identidade
    pendencia = json.loads(Path(resultado['arquivo_pendencia']).read_text())
    assert pendencia['sha256_imagem'] == hashlib.sha256(Path(resultado['arquivo_imagem']).read_bytes()).hexdigest()
    assert not arquivo_publico(tmp_path, Path(resultado['arquivo_imagem']).relative_to(tmp_path))
    assert not (tmp_path / 'resultados/logs').exists()
    gerador.gerar_comunicado_oficial.assert_called_once()
    with pytest.raises(ImageAccessError) as erro:
        exigir_revisor_imagem()
    assert erro.value.status_code == 503


def test_falha_identidade_impede_geracao(monkeypatch):
    monkeypatch.setattr(local, 'identidade_windows', Mock(side_effect=RuntimeError('Identidade indisponível')))
    gerador = Mock(side_effect=AssertionError('Não chamar provedor'))
    monkeypatch.setattr('src.image_generation.ImageGenerator', gerador)
    with pytest.raises(RuntimeError):
        local.gerar_teste_local(True, True)
    gerador.assert_not_called()
