"""RF07: aprovação/persistência reais; mecanismos de voz simulados."""
import json
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.audio import AudioProcessor
from src.audit import AuditLogger
from src import resolver_caminho


def gravar_wav(caminho):
    with wave.open(str(caminho), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x01\x00" * 8000)


@pytest.fixture
def tts(tmp_path, monkeypatch):
    proc = AudioProcessor.__new__(AudioProcessor)
    proc.config = {}
    proc.audios_dir = tmp_path / "audios"
    proc.tts_voice = "pt-BR-AntonioNeural"
    logger = AuditLogger(str(tmp_path / "logs"))
    identificador = logger.registrar_execucao("texto", "", "teste", "teste", "teste", {}, {}, 0)
    texto = " RG não localizado. "
    monkeypatch.setenv("TTS_PROVIDER", "sapi5")
    provider = Mock(side_effect=lambda texto, caminho: (gravar_wav(caminho), "Microsoft Maria")[1])
    monkeypatch.setattr(proc, "_sintetizar_sapi5", provider)
    return proc, logger, identificador, texto, provider


def aprovar(logger, identificador, texto):
    assert logger.atualizar_decisao_humana(identificador, "APROVADO", "Conferido em teste", "Operador teste", texto)


def test_aprovacao_exata_wav_metadados_auditoria(tts):
    proc, logger, identificador, texto, provider = tts
    aprovar(logger, identificador, texto)
    resultado = proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)
    assert resultado["sucesso"]
    assert resultado["formato"] == "wav"
    assert resultado["voz_utilizada"] == "Microsoft Maria"
    assert resultado["duracao_segundos"] == 1
    assert resultado["hash_texto_aprovado"] == logger.hash_texto(texto)
    assert resultado["hash_texto_sintetizado"] != resultado["hash_texto_aprovado"]
    assert "informação pendente" in provider.call_args.args[0]
    assert resultado["aviso_acessibilidade_aplicado"]
    metadata = json.loads(resolver_caminho(resultado["caminho_metadados"]).read_text(encoding="utf-8"))
    assert metadata["id_execucao"] == resultado["id_execucao"]
    assert metadata["detalhes_completos"]["id_execucao_aprovacao"] == identificador
    assert metadata["detalhes_completos"]["sha256_audio"] == resultado["sha256_audio"]
    assert metadata["decisao_humana"]["status"] == "APROVADO"
    aprovado = json.loads((logger.log_dir / f"{identificador}.json").read_text(encoding="utf-8"))
    assert aprovado["texto_final"] == texto
    assert aprovado["decisao_humana"]["hash_texto_aprovado"] == resultado["hash_texto_aprovado"]


@pytest.mark.parametrize("caso", ["pendente", "rejeitado", "corrigido", "texto_modificado", "espacos", "sem_id", "hash_alterado"])
def test_bloqueios(tts, caso):
    proc, logger, identificador, texto, provider = tts
    if caso != "pendente":
        aprovar(logger, identificador, texto)
    if caso in {"rejeitado", "corrigido"}:
        logger.atualizar_decisao_humana(identificador, caso.upper(), "Revisar")
    elif caso == "texto_modificado":
        texto += "Outro conteúdo."
    elif caso == "espacos":
        texto = texto.strip()
    elif caso == "sem_id":
        identificador = None
    elif caso == "hash_alterado":
        arquivo = logger.log_dir / f"{identificador}.json"
        registro = json.loads(arquivo.read_text(encoding="utf-8"))
        registro["decisao_humana"]["hash_texto_aprovado"] = "invalido"
        arquivo.write_text(json.dumps(registro), encoding="utf-8")
    resultado = proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)
    assert not resultado["sucesso"]
    assert resultado["codigo_erro"] == "texto_nao_aprovado"
    provider.assert_not_called()
    registro = json.loads(resolver_caminho(resultado["caminho_metadados"]).read_text(encoding="utf-8"))
    assert not registro["resultado_resumo"]["sucesso"]


@pytest.mark.parametrize("caso", ["erro", "ausente", "vazio", "formato", "truncado", "revogado"])
def test_falhas_sem_audio_ficticio(tts, caso):
    proc, logger, identificador, texto, provider = tts
    aprovar(logger, identificador, texto)
    if caso == "erro":
        provider.side_effect = RuntimeError("segredo-nao-propagar")
    elif caso == "ausente":
        provider.side_effect = lambda *args: "Maria"
    elif caso in {"vazio", "formato", "truncado"}:
        def invalido(texto, caminho):
            if caso == "vazio":
                Path(caminho).touch()
            elif caso == "formato":
                Path(caminho).write_bytes(b"invalido" * 30)
            else:
                gravar_wav(caminho)
                Path(caminho).write_bytes(Path(caminho).read_bytes()[:60])
            return "Maria"
        provider.side_effect = invalido
    else:
        def revogar(texto, caminho):
            gravar_wav(caminho)
            logger.atualizar_decisao_humana(identificador, "REJEITADO", "Revogado")
            return "Maria"
        provider.side_effect = revogar
    resultado = proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)
    assert not resultado["sucesso"]
    assert not list(proc.audios_dir.glob("*.wav"))
    assert "segredo-nao-propagar" not in json.dumps(resultado)


def test_aprovacao_sem_texto_e_traversal_bloqueados(tts):
    _, logger, identificador, texto, _ = tts
    assert not logger.atualizar_decisao_humana(identificador, "APROVADO", "Teste")
    assert not logger.obter_aprovacao_texto("../config", texto)


def test_saida_fora_do_diretorio_bloqueada(tts):
    proc, logger, identificador, texto, provider = tts
    aprovar(logger, identificador, texto)
    resultado = proc.sintetizar_minuta_audio(texto, "../fora.wav", identificador, logger)
    assert not resultado["sucesso"]
    provider.assert_not_called()


def test_provedor_invalido_e_edge_opcional(tts, monkeypatch):
    proc, logger, identificador, texto, provider = tts
    aprovar(logger, identificador, texto)
    monkeypatch.setenv("TTS_PROVIDER", "invalido")
    assert not proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)["sucesso"]
    monkeypatch.setenv("TTS_PROVIDER", "edge-tts")
    async def edge_mock(texto, caminho):
        Path(caminho).write_bytes(b"mock-mp3" * 20)
    monkeypatch.setattr(proc, "_sintetizar_edge_tts", edge_mock)
    monkeypatch.setattr(proc, "_validar_audio_tts", lambda *args: 1.0)
    resultado = proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)
    assert resultado["sucesso"] and resultado["formato"] == "mp3"
    provider.assert_not_called()


def test_falha_auditoria_nao_libera_arquivo(tts, monkeypatch):
    proc, logger, identificador, texto, _ = tts
    aprovar(logger, identificador, texto)
    monkeypatch.setattr(logger, "registrar_execucao", Mock(side_effect=OSError()))
    resultado = proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)
    assert not resultado["sucesso"]
    assert resultado["codigo_erro"] == "falha_auditoria"
    assert not list(proc.audios_dir.glob("*.wav"))


def test_aprovacao_corrompida_bloqueia(tts):
    proc, logger, identificador, texto, provider = tts
    (logger.log_dir / f"{identificador}.json").write_text("[]", encoding="utf-8")
    assert not proc.sintetizar_minuta_audio(texto, id_execucao=identificador, audit_logger=logger)["sucesso"]
    provider.assert_not_called()


def test_sapi5_comando_estatico_entrada_json(tts, monkeypatch):
    import base64
    import src.audio as audio
    proc, _, _, _, _ = tts
    run = Mock(return_value=Mock(returncode=0, stdout=b'{"voz":"Microsoft Maria"}'))
    monkeypatch.setattr(audio.subprocess, "run", run)
    texto = "Texto com aspas e $(comando) não deve executar código."
    assert AudioProcessor._sintetizar_sapi5(proc, texto, "teste.wav") == "Microsoft Maria"
    args, kwargs = run.call_args
    script = base64.b64decode(args[0][-1]).decode("utf-16le")
    assert texto not in script
    assert json.loads(kwargs["input"])["texto"] == texto
    assert "Language=416" in script
    assert kwargs["timeout"] == 120
