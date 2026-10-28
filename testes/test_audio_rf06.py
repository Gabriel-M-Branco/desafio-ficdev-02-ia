"""RF06 offline: WAV real local, provedor STT inteiramente simulado."""
import json
import sys
import types
import wave
from unittest.mock import Mock

import pytest

from src.audio import AudioProcessor


@pytest.fixture
def audio(tmp_path, monkeypatch):
    path = tmp_path / "entrada.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 8000)
    # Evita inicializacao de servicos/diretorios: apenas metodos RF06.
    proc = AudioProcessor.__new__(AudioProcessor)
    proc.config = {"generation_params": {"timeout_seconds": 7}}
    proc.stt_model = "openai/whisper-large-v3-turbo"
    monkeypatch.setenv("HF_TOKEN", "token-teste")
    monkeypatch.setenv("EXECUTION_MODE", "auto")
    monkeypatch.setenv("STT_PROVIDER", "huggingface")
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(InferenceClient=factory))
    return proc, path, client, factory


def test_transcricao_real_do_provedor_preservada(audio):
    proc, path, client, factory = audio
    text = "  Ana Souza\n protocolo 9876-123456 em 3 de maio de 2025.  "
    client.automatic_speech_recognition.return_value = types.SimpleNamespace(text=text)
    result = proc.transcrever_audio(str(path))
    assert result["sucesso"]
    assert result["transcricao_bruta"] == text
    assert result["transcricao_revisada"] == "Ana Souza protocolo 9876-123456 em 3 de maio de 2025."
    assert not result["comparacao_gabarito"]["todos_campos_criticos_conferidos"]
    assert result["metadados"]["duracao_segundos"] == 1
    assert result["metadados"]["idioma_detectado"] == "não localizado"
    assert result["metadados"]["modelo_stt"] == proc.stt_model
    assert result["exige_confirmacao_humana"]
    factory.assert_called_once_with(token="token-teste", timeout=7)
    client.automatic_speech_recognition.assert_called_once_with(str(path), model=proc.stt_model)


@pytest.mark.parametrize("kind", ["ausente", "extensao", "vazio", "corrompido", "grande", "diretorio"])
def test_arquivo_invalido(audio, kind, monkeypatch):
    proc, path, client, _ = audio
    if kind == "ausente":
        path = path.with_name("ausente.wav")
    elif kind == "extensao":
        path = path.rename(path.with_suffix(".txt"))
    elif kind == "diretorio":
        path = path.parent
    elif kind == "grande":
        monkeypatch.setattr("src.audio.MAX_AUDIO_SIZE_BYTES", 10)
    else:
        path.write_bytes(b"" if kind == "vazio" else b"invalido")
    assert not proc.transcrever_audio(str(path))["sucesso"]
    client.automatic_speech_recognition.assert_not_called()


@pytest.mark.parametrize("status,code", [(401, "autenticacao"), (403, "autenticacao"),
                                         (429, "limite_requisicoes"), (503, "falha_provedor")])
def test_erros_http_sem_segredos(audio, status, code):
    proc, path, client, _ = audio
    error = RuntimeError("token-teste")
    error.response = types.SimpleNamespace(status_code=status)
    client.automatic_speech_recognition.side_effect = error
    result = proc.transcrever_audio(str(path))
    assert not result["sucesso"] and result["codigo_erro"] == code
    assert "token-teste" not in json.dumps(result)


def test_timeout(audio):
    proc, path, client, _ = audio
    client.automatic_speech_recognition.side_effect = TimeoutError()
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "timeout"


def test_idioma_informado_pelo_provedor(audio):
    proc, path, client, _ = audio
    client.automatic_speech_recognition.return_value = {"text": "Olá, Ana.", "language": "pt"}
    assert proc.transcrever_audio(str(path))["metadados"]["idioma_detectado"] == "pt"


def test_resposta_malformada(audio):
    proc, path, client, _ = audio
    client.automatic_speech_recognition.return_value = None
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "falha_provedor"


def test_memoria_local_preserva_causa_sem_segredo(audio, monkeypatch):
    proc, path, _, _ = audio
    monkeypatch.setenv("STT_PROVIDER", "local")
    monkeypatch.setenv("HF_TOKEN", "hf_segredo_ficticio")
    def falhar(_):
        raise RuntimeError("mkl_malloc: failed to allocate memory hf_segredo_ficticio")
    monkeypatch.setattr(proc, "_transcrever_local", falhar)
    r = proc.transcrever_audio(str(path))
    assert not r["sucesso"] and r["codigo_erro"] == "memoria_insuficiente"
    assert "mkl_malloc" in r["erro"] and "paginação" in r["erro"]
    assert r["diagnostico"]["tipo_excecao"] == "RuntimeError"
    assert r["diagnostico"]["origem"][-1]["funcao"] == "falhar"
    assert "hf_segredo_ficticio" not in json.dumps(r)


def test_dependencia_ausente(audio, monkeypatch):
    proc, path, _, _ = audio
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "dependencia_ausente"


def test_gabarito_ausente(audio, monkeypatch, tmp_path):
    proc, _, _, _ = audio
    monkeypatch.setattr("src.audio.resolver_caminho", lambda _: tmp_path / "ausente.json")
    assert not proc.comparar_com_gabarito("qualquer texto")["todos_campos_criticos_conferidos"]


@pytest.mark.parametrize("text", ["", " \n ", None, 123])
def test_resposta_vazia(audio, text):
    proc, path, client, _ = audio
    client.automatic_speech_recognition.return_value = {"text": text}
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "resposta_vazia"


@pytest.mark.parametrize("mode,token", [("mock", "token-teste"), ("auto", "")])
def test_sem_provedor_nao_inventa(audio, monkeypatch, mode, token):
    proc, path, client, _ = audio
    monkeypatch.setenv("EXECUTION_MODE", mode)
    monkeypatch.setenv("HF_TOKEN", token)
    assert not proc.transcrever_audio(str(path))["sucesso"]
    client.automatic_speech_recognition.assert_not_called()


def test_gabarito_datas_nomes_numeros(audio):
    proc, _, _, _ = audio
    from src import resolver_caminho
    reference = json.loads(resolver_caminho("dados/gabaritos/gabarito_audio.json").read_text(encoding="utf-8"))
    text = reference["transcricao_referencia"]
    assert proc.comparar_com_gabarito(text)["todos_campos_criticos_conferidos"]
    text = text.replace("Marcos", "Maria").replace("2026-000142", "2026-0001429").replace("14 de outubro", "15 de outubro")
    result = proc.comparar_com_gabarito(text)
    assert set(result["campos_divergentes_ou_ausentes"]) == {"solicitante", "protocolo", "data"}
    assert not proc.comparar_com_gabarito("")["todos_campos_criticos_conferidos"]


@pytest.fixture
def local(audio, monkeypatch):
    proc, path, hf, _ = audio
    monkeypatch.setenv("STT_PROVIDER", "local")
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.setenv("EXECUTION_MODE", "mock")
    model = Mock()
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=factory))
    return proc, path, hf, model, factory


def test_local_sem_token_sem_rede_preserva_contrato(local):
    proc, path, hf, model, factory = local
    model.transcribe.return_value = (
        iter([types.SimpleNamespace(text=" Olá, Ana."), types.SimpleNamespace(text="\n Protocolo 42.")]),
        types.SimpleNamespace(language="pt"),
    )
    result = proc.transcrever_audio(str(path))
    assert result["sucesso"]
    assert result["transcricao_bruta"] == " Olá, Ana.\n Protocolo 42."
    assert result["transcricao_revisada"] == "Olá, Ana. Protocolo 42."
    assert result["provedor"] == "faster-whisper"
    assert result["origem_processamento"] == "local"
    assert result["metadados"]["modelo_stt"] == "small"
    assert result["metadados"]["idioma_detectado"] == "pt"
    assert result["metadados"]["duracao_segundos"] == 1
    assert result["tempo_processamento_segundos"] >= 0
    assert result["exige_confirmacao_humana"]
    assert not result["comparacao_gabarito"]["todos_campos_criticos_conferidos"]
    factory.assert_called_once_with("small", device="cpu", compute_type="int8", local_files_only=True)
    model.transcribe.assert_called_once_with(str(path), language="pt")
    hf.automatic_speech_recognition.assert_not_called()


def test_local_modelo_ausente_nao_baixa(local):
    proc, path, hf, _, factory = local
    factory.side_effect = FileNotFoundError("modelo fora do cache")
    result = proc.transcrever_audio(str(path))
    assert not result["sucesso"]
    assert result["codigo_erro"] == "modelo_local_indisponivel"
    hf.automatic_speech_recognition.assert_not_called()


def test_local_dependencia_ausente(local, monkeypatch):
    proc, path, _, _, _ = local
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "dependencia_ausente"


def test_local_erro_durante_iteracao(local):
    proc, path, _, model, _ = local
    def segmentos():
        yield types.SimpleNamespace(text="parcial")
        raise RuntimeError("token-teste")
    model.transcribe.return_value = (segmentos(), types.SimpleNamespace(language="pt"))
    result = proc.transcrever_audio(str(path))
    assert not result["sucesso"] and result["codigo_erro"] == "falha_provedor"
    assert "transcricao_bruta" not in result
    assert "token-teste" not in json.dumps(result)


def test_local_sem_fala(local):
    proc, path, _, model, _ = local
    model.transcribe.return_value = (iter([]), types.SimpleNamespace(language="pt"))
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "resposta_vazia"


def test_local_arquivo_invalido_nao_carrega_modelo(local):
    proc, path, _, _, factory = local
    path.write_bytes(b"invalido")
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "arquivo_invalido"
    factory.assert_not_called()


def test_provedor_invalido(audio, monkeypatch):
    proc, path, hf, _ = audio
    monkeypatch.setenv("STT_PROVIDER", "invalido")
    assert proc.transcrever_audio(str(path))["codigo_erro"] == "provedor_invalido"
    hf.automatic_speech_recognition.assert_not_called()


def test_metadados_mp3_sem_tags(audio, monkeypatch):
    proc, path, _, _ = audio
    path = path.rename(path.with_suffix(".mp3"))
    class SemTags(dict):
        info = types.SimpleNamespace(length=89.16)
    monkeypatch.setitem(sys.modules, "mutagen", types.SimpleNamespace(File=lambda _: SemTags()))
    assert proc.extrair_metadados_audio(str(path))["duracao_segundos"] == 89.16
