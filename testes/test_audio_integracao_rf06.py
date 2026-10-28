"""Persistencia e auditoria RF06 reais em tmp_path; STT simulado, sem rede."""
import json
from unittest.mock import Mock

import pytest

from src import resolver_caminho
from src.audio import AudioProcessor
from src.audit import AuditLogger


@pytest.fixture
def fluxo(tmp_path, monkeypatch):
    logger = AuditLogger(str(tmp_path / "logs"))
    proc = AudioProcessor.__new__(AudioProcessor)
    proc.transcrever_audio = Mock()
    proc.config = {"paths": {"dados_processados": str(tmp_path / "processados")}}
    proc.stt_model = "small"
    monkeypatch.setenv("STT_PROVIDER", "local")
    return lambda: proc.processar_com_auditoria(logger), proc, logger, tmp_path


def test_sucesso_persiste_transcricao_comparacao_auditoria(fluxo):
    client, proc, logger, _ = fluxo
    proc.transcrever_audio.return_value = {
        "sucesso": True, "provedor": "faster-whisper",
        "metadados": {"modelo_stt": "small"},
        "transcricao_bruta": "mensagem ficticia", "transcricao_revisada": "mensagem ficticia",
        "comparacao_gabarito": {"todos_campos_criticos_conferidos": False},
    }
    result = client()
    arquivo = resolver_caminho(result["arquivo_transcricao"])
    salvo = json.loads(arquivo.read_text(encoding="utf-8"))
    assert salvo["transcricao_bruta"] == result["transcricao_bruta"]
    assert salvo["transcricao_revisada"] == result["transcricao_revisada"]
    assert salvo["comparacao_gabarito"] == result["comparacao_gabarito"]
    registro = json.loads((logger.log_dir / f"{result['id_execucao']}.json").read_text(encoding="utf-8"))
    assert registro["provedor"] == "faster-whisper"
    assert registro["modelo"] == "small"
    assert registro["duracao_segundos"] >= 0
    assert registro["resultado_resumo"]["sucesso"]
    assert registro["detalhes_completos"]["arquivo_transcricao"] == result["arquivo_transcricao"]
    assert registro["decisao_humana"]["status"] == "pendente_revisao"
    assert json.loads(logger.trail_file.read_text(encoding="utf-8"))["id_execucao"] == result["id_execucao"]


def test_falha_stt_auditada_sem_falso_sucesso(fluxo):
    client, proc, logger, tmp = fluxo
    proc.transcrever_audio.return_value = {"sucesso": False, "codigo_erro": "timeout", "erro": "Falha STT"}
    result = client()
    registro = json.loads((logger.log_dir / f"{result['id_execucao']}.json").read_text(encoding="utf-8"))
    assert not registro["resultado_resumo"]["sucesso"]
    assert registro["erros"] == ["timeout"]
    assert "arquivo_transcricao" not in result
    assert not (tmp / "processados").exists()


def test_falha_gravacao_auditada(fluxo):
    client, proc, logger, tmp = fluxo
    bloqueio = tmp / "arquivo_nao_diretorio"
    bloqueio.write_text("teste", encoding="utf-8")
    proc.config["paths"]["dados_processados"] = str(bloqueio)
    proc.transcrever_audio.return_value = {"sucesso": True, "transcricao_bruta": "teste"}
    result = client()
    assert not result["sucesso"]
    assert result["codigo_erro"] == "falha_persistencia"
    assert "arquivo_transcricao" not in result
    registro = json.loads((logger.log_dir / f"{result['id_execucao']}.json").read_text(encoding="utf-8"))
    assert not registro["resultado_resumo"]["sucesso"]
    assert registro["erros"] == ["falha_persistencia"]
