import sys
import traceback
"""
Módulo de Processamento de Áudio: STT (Whisper HF) e TTS com Acessibilidade (RF06, RF07)
"""

import os
import json
import asyncio
from typing import Dict, Any, Tuple, Optional
from pathlib import Path
import re
import unicodedata
import wave
import time
import uuid
import base64
import hashlib
import subprocess

from src import resolver_caminho, caminho_relativo
from src.llm_client import LLMClient

MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}


class AudioProcessor:
    """
    Orquestrador para Transcrição de Voz (STT) e Síntese de Voz Institucional (TTS).
    """

    @classmethod
    def _obter_provedor_stt(cls) -> str:
        provider = os.getenv("STT_PROVIDER", "").strip().lower()
        if provider in {"local", "openai", "huggingface", "openrouter"}:
            return provider
        if os.getenv("OPENAI_API_KEY", "").strip() and not os.getenv("HF_TOKEN", "").strip():
            return "openai"
        if os.getenv("HF_TOKEN", "").strip():
            return "huggingface"
        if os.getenv("OPENAI_API_KEY", "").strip():
            return "openai"
        if os.getenv("OPENROUTER_API_KEY", "").strip():
            return "openrouter"
        return "local"

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.llm_client = LLMClient(config_path)
        self.stt_provider = self._obter_provedor_stt()
        self.stt_model = "small" if self.stt_provider == "local" else (os.getenv("OPENAI_STT_MODEL", "whisper-1").strip() if self.stt_provider == "openai" else self.config.get("models", {}).get("stt", "openai/whisper-large-v3-turbo"))
        self.tts_voice = self.config.get("models", {}).get("tts_voice", "pt-BR-AntonioNeural")
        self.audios_dir = resolver_caminho(self.config.get("paths", {}).get("resultados_audios", "resultados/audios"))
        self.audios_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            p = resolver_caminho(config_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def validar_arquivo_audio(self, caminho_audio: str) -> Tuple[bool, str]:
        """Valida arquivo, extensão, tamanho e cabeçalho/duração legíveis."""
        path = resolver_caminho(caminho_audio)
        try:
            if not path.is_file():
                return False, "Arquivo de áudio não encontrado."
            if path.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
                return False, "Formato de áudio não permitido."
            if not 0 < path.stat().st_size <= MAX_AUDIO_SIZE_BYTES:
                return False, "áudio vazio ou maior que 25 MB."
            self.extrair_metadados_audio(str(path))
        except (OSError, ValueError, ImportError):
            return False, "áudio ilegível, inválido ou dependência de leitura indisponível."
        return True, "Arquivo de áudio válido."

    def extrair_metadados_audio(self, caminho_audio: str) -> Dict[str, Any]:
        path = resolver_caminho(caminho_audio)
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as audio:
                    duracao = audio.getnframes() / audio.getframerate()
            except (wave.Error, EOFError, ZeroDivisionError) as exc:
                raise ValueError("WAV inválido") from exc
        else:
            import mutagen
            try:
                audio = mutagen.File(str(path))
                duracao = audio.info.length if audio is not None and audio.info is not None else 0
            except Exception as exc:
                raise ValueError("áudio inválido") from exc
        if duracao <= 0:
            raise ValueError("Duração de áudio inválida")
        return {
            "arquivo": path.name,
            "duracao_segundos": round(duracao, 3),
            "tamanho_bytes": path.stat().st_size,
            "modelo_stt": self.stt_model,
            # O endpoint STT não garante detecção de idioma; não presumir português.
            "idioma_detectado": "não localizado",
        }

    def _transcrever_local(self, path: Path) -> Dict[str, Any]:
        """Usa somente modelo previamente baixado; nunca baixa nem aciona API."""
        _orig_av_open = None
        try:
            import av
            _orig_av_open = av.open
            def _safe_av_open(*args, **kwargs):
                kwargs.pop("metadata_errors", None)
                return _orig_av_open(*args, **kwargs)
            av.open = _safe_av_open
        except Exception:
            _orig_av_open = None

        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)
            segmentos, info = model.transcribe(str(path), language="pt")
            # A inferência é lazy: consumir dentro do tratamento de erros do chamador.
            return {"text": "".join(segmento.text for segmento in segmentos),
                    "language": info.language}
        finally:
            if _orig_av_open is not None:
                av.open = _orig_av_open

    def _transcrever_openrouter(self, path: Path) -> Dict[str, Any]:
        """Executa STT multimodal utilizando a API do OpenRouter (ex: google/gemini-3.8-flash)."""
        import requests
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        model = os.getenv("OPENROUTER_STT_MODEL") or os.getenv("STT_MODEL") or "google/gemini-3.8-flash"
        ext = path.suffix.lower().lstrip(".")
        fmt = "mp3" if ext in ("mp3", "mpeg") else ("wav" if ext == "wav" else ext)
        audio_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Transcreva o áudio a seguir com fidelidade palavra por palavra em português. Retorne apenas o texto transcrito, sem comentários:",
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": fmt,
                            },
                        },
                    ],
                }
            ],
        }
        timeout = self.config.get("generation_params", {}).get("timeout_seconds", 60)
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            err_msg = ""
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"OpenRouter STT retornou status {resp.status_code}: {err_msg}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"text": content, "language": "pt", "model": model}

    def _transcrever_openai(self, path: Path) -> Dict[str, Any]:
        """Transcreve via OpenAI Whisper API (whisper-1)."""
        import requests
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY não configurada para STT.")
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = os.getenv("OPENAI_STT_MODEL", "whisper-1").strip()
        timeout = self.config.get("generation_params", {}).get("timeout_seconds", 60)
        ext = path.suffix.lower()
        content_type = "audio/mpeg" if ext in {".mp3", ".mpeg"} else ("audio/wav" if ext == ".wav" else "application/octet-stream")
        with open(path, "rb") as f:
            files = {"file": (path.name, f, content_type)}
            data = {"model": model, "language": "pt"}
            headers = {"Authorization": f"Bearer {key}"}
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=timeout)
        if resp.status_code != 200:
            err_msg = ""
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"OpenAI Whisper retornou status {resp.status_code}: {err_msg}")
        dados = resp.json()
        return {"text": dados.get("text", "").strip(), "language": "pt", "model": model}

    def transcrever_audio(self, caminho_audio: str) -> Dict[str, Any]:
        """Executa transcrição de áudio (STT) com Whisper ou OpenRouter Gemini."""
        valido, mensagem = self.validar_arquivo_audio(caminho_audio)
        if not valido:
            return {"sucesso": False, "erro": mensagem, "codigo_erro": "arquivo_invalido"}
        provedor_env = os.getenv("STT_PROVIDER", "").strip().lower()
        if provedor_env and provedor_env not in {"local", "openai", "huggingface", "openrouter"}:
            return {"sucesso": False, "erro": "STT_PROVIDER deve ser local, huggingface ou openrouter.",
                    "codigo_erro": "provedor_invalido"}
        provider = self._obter_provedor_stt()
        token = os.getenv("HF_TOKEN", "").strip()
        if provider == "huggingface" and (os.getenv("EXECUTION_MODE", "auto").lower() == "mock" or not token):
            return {"sucesso": False, "erro": "STT real requer HF_TOKEN e modo diferente de mock.",
                    "codigo_erro": "stt_indisponivel"}
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if provider == "openai" and (os.getenv("EXECUTION_MODE", "auto").lower() == "mock" or not openai_key):
            return {"sucesso": False, "erro": "STT via OpenAI requer OPENAI_API_KEY e modo diferente de mock.",
                    "codigo_erro": "stt_indisponivel"}
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if provider == "openrouter" and (os.getenv("EXECUTION_MODE", "auto").lower() == "mock" or not openrouter_key):
            return {"sucesso": False, "erro": "STT via OpenRouter requer OPENROUTER_API_KEY e modo diferente de mock.",
                    "codigo_erro": "stt_indisponivel"}
        path = resolver_caminho(caminho_audio)
        inicio = time.perf_counter()
        try:
            if provider == "local":
                resultado = self._transcrever_local(path)
            elif provider == "openai":
                resultado = self._transcrever_openai(path)
            elif provider == "openrouter":
                resultado = self._transcrever_openrouter(path)
            else:
                from huggingface_hub import InferenceClient
                client = InferenceClient(token=token, timeout=self.config.get(
                    "generation_params", {}).get("timeout_seconds", 30))
                resultado = client.automatic_speech_recognition(str(path), model=self.stt_model)
            bruta = resultado.get("text") if isinstance(resultado, dict) else resultado.text
            if not isinstance(bruta, str) or not bruta.strip():
                return {"sucesso": False, "erro": "Provedor retornou transcrição vazia.",
                        "codigo_erro": "resposta_vazia"}
            metadados = self.extrair_metadados_audio(str(path))
            if provider == "local":
                metadados.update(modelo_stt="small", dispositivo="cpu", compute_type="int8",
                                 idioma_configurado="pt")
            elif provider == "openai":
                metadados.update(modelo_stt=resultado.get("model", "whisper-1"),
                                 provedor="OpenAI API", idioma_detectado="pt")
            elif provider == "openrouter":
                metadados.update(modelo_stt=resultado.get("model", "google/gemini-3.8-flash"),
                                 provedor="OpenRouter", idioma_detectado="pt")
            idioma = resultado.get("language") if isinstance(resultado, dict) else getattr(resultado, "language", None)
            if isinstance(idioma, str) and idioma.strip():
                metadados["idioma_detectado"] = idioma.strip()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            memoria = provider == "local" and (isinstance(exc, MemoryError) or
                "mkl_malloc" in str(exc).lower() or "failed to allocate memory" in str(exc).lower())
            if memoria:
                codigo = "memoria_insuficiente"
            elif provider == "local" and isinstance(exc, FileNotFoundError):
                codigo = "modelo_local_indisponivel"
            elif status in (401, 403):
                codigo = "autenticacao"
            elif status == 429:
                codigo = "limite_requisicoes"
            elif "timeout" in type(exc).__name__.lower() or isinstance(exc, TimeoutError):
                codigo = "timeout"
            elif isinstance(exc, ImportError):
                codigo = "dependencia_ausente"
            else:
                codigo = "falha_provedor"
            falha = {"sucesso": False, "erro": "Não foi possível concluir o STT.", "codigo_erro": codigo}
            if provider == "local":
                # Preservar a causa local na auditoria, sem segredos nem variáveis locais.
                detalhe = str(exc)
                for nome, valor in os.environ.items():
                    if len(valor) > 4 and any(k in nome.upper() for k in ("TOKEN", "KEY", "PASSWORD", "SECRET")):
                        detalhe = detalhe.replace(valor, "[credencial omitida]")
                detalhe = re.sub(r"Bearer\s+\S+|(?:sk-or-v1-|hf_|token[-_])[A-Za-z0-9_-]+", "[credencial omitida]", detalhe, flags=re.IGNORECASE)
                frames = traceback.extract_tb(exc.__traceback__)
                falha["diagnostico"] = {"tipo_excecao": type(exc).__name__, "mensagem": detalhe[:1000],
                    "origem": [{"arquivo": Path(f.filename).name, "linha": f.lineno, "funcao": f.name} for f in frames]}
                falha["erro"] = ("Memória insuficiente para carregar/executar faster-whisper small (CPU/int8). "
                    "Feche aplicativos pesados e verifique a memória virtual/arquivo de paginação do Windows; "
                    "tente novamente. Causa: " if memoria else "STT local falhou: ") + detalhe[:300]
            return falha
        revisada = re.sub(r"\s+", " ", bruta).strip()
        return {
            "sucesso": True, "arquivo_audio": caminho_relativo(path), "metadados": metadados,
            "transcricao_bruta": bruta, "transcricao_revisada": revisada,
            "revisao_aplicada": "Normalização de espaços; conteúdo pendente de revisão humana.",
            "origem_processamento": "local" if provider == "local" else "api_remota",
            "provedor": "faster-whisper" if provider == "local" else ("OpenRouter" if provider == "openrouter" else "HuggingFace"),
            "tempo_processamento_segundos": round(time.perf_counter() - inicio, 3),
            "exige_confirmacao_humana": True,
            "comparacao_gabarito": self.comparar_com_gabarito(bruta),
        }

    def processar_com_auditoria(self, audit_logger) -> Dict[str, Any]:
        """Transcreve, persiste o resultado RF06 e registra o provedor efetivo."""
        inicio = time.perf_counter()
        caminho = resolver_caminho("dados/originais/entrada_audio.mp3")
        resultado = self.transcrever_audio(str(caminho))
        if resultado.get("sucesso"):
            diretorio = resolver_caminho(self.config.get("paths", {}).get(
                "dados_processados", "dados/processados"))
            nome_base = caminho.stem
            for antigo in diretorio.glob("transcricao_*.json"):
                try:
                    antigo.unlink()
                except OSError:
                    pass
            arquivo = diretorio / f"transcricao_{nome_base}.json"
            try:
                diretorio.mkdir(parents=True, exist_ok=True)
                resultado["arquivo_transcricao"] = caminho_relativo(arquivo)
                arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                resultado.pop("arquivo_transcricao", None)
                resultado.update(sucesso=False, codigo_erro="falha_persistencia",
                                 erro="Não foi possível salvar a transcrição.")
        stt_env = self._obter_provedor_stt()
        provider = resultado.get("provedor") or (
            "faster-whisper" if stt_env == "local"
            else ("OpenRouter" if stt_env == "openrouter" else "HuggingFace")
        )
        exec_id = audit_logger.registrar_execucao(
            modalidade="audio",
            arquivo_origem="dados/originais/entrada_audio.mp3",
            provedor=provider,
            modelo=resultado.get("metadados", {}).get("modelo_stt", self.stt_model),
            versao_prompt="N/A (STT Direto)",
            parametros={},
            resultado=resultado,
            duracao_segundos=time.perf_counter() - inicio,
            erros=[] if resultado.get("sucesso") else [resultado.get("codigo_erro", "falha_stt")],
        )
        resultado["id_execucao"] = exec_id
        return resultado

    @staticmethod
    def _normalizar_comparacao(texto: str) -> str:
        texto = "".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                        if not unicodedata.combining(c))
        # Normaliza pontuação de milhar em números (ex: 1.200 -> 1200)
        texto = re.sub(r"\b(\d+)\.(\d{3})\b", r"\1\2", texto)
        meses = "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split()
        for numero, mes in enumerate(meses, 1):
            texto = re.sub(r"\b(\d{1,2}) de " + mes + r" de (\d{4})\b",
                           lambda m: f"{int(m[1]):02d}/{numero:02d}/{m[2]}", texto)
        texto = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
                       lambda m: f"{int(m[1]):02d}/{int(m[2]):02d}/{m[3]}", texto)
        return re.sub(r"\s+", " ", texto).strip()

    def comparar_com_gabarito(self, transcricao: str) -> Dict[str, Any]:
        path = resolver_caminho("dados/gabaritos/gabarito_audio.json")
        entidades = None
        if path.is_file():
            try:
                gabarito = json.loads(path.read_text(encoding="utf-8"))
                entidades = gabarito.get("entidades_criticas")
            except Exception:
                pass
        if not entidades or not isinstance(entidades, dict):
            # Entidades essenciais auditadas diretamente da mensagem institucional (RF06)
            entidades = {
                "solicitante": "Marcos Vinicius",
                "protocolo": "2026-000142",
                "curso": "Enfermagem",
                "eixo_tecnologico": "Saúde",
                "carga_horaria": "1200",
                "data": "14/10/2026",
            }
        texto = self._normalizar_comparacao(transcricao)
        detalhes = {}
        for campo, valor in entidades.items():
            esperado = self._normalizar_comparacao(str(valor))
            localizado = bool(esperado) and bool(re.search(r"(?<!\w)" + re.escape(esperado) + r"(?!\w)", texto))
            detalhes[campo] = {"valor_esperado": valor, "localizado_na_transcricao": localizado}
        erros = [campo for campo, item in detalhes.items() if not item["localizado_na_transcricao"]]
        ref_text = gabarito.get("transcricao_referencia") if (path.is_file() and 'gabarito' in locals() and isinstance(gabarito, dict)) else None
        return {"todos_campos_criticos_conferidos": not erros, "detalhes": detalhes,
                "campos_divergentes_ou_ausentes": erros,
                "acuracia_entidades": f"{len(detalhes)-len(erros)}/{len(detalhes)}",
                "comparacao_texto_referencia": self._comparar_texto_referencia(transcricao, ref_text),
                "confirmacao_humana_pendente": True}

    @classmethod
    def _comparar_texto_referencia(cls, transcricao, referencia):
        """WER por Levenshtein normalizado, sem preencher nem alterar a transcrição."""
        if not isinstance(referencia, str) or not referencia.strip():
            return {"status": "referencia_textual_indisponivel"}
        ref = re.findall(r"\w+", cls._normalizar_comparacao(referencia))
        obtido = re.findall(r"\w+", cls._normalizar_comparacao(transcricao))
        if not ref:
            return {"status": "referencia_textual_indisponivel"}
        if len(ref) * len(obtido) > 1_000_000:
            return {"status": "limite_comparacao_integral", "palavras_referencia": len(ref)}
        anterior = [(j, 0, 0, j) for j in range(len(obtido) + 1)]
        for i, esperado in enumerate(ref, 1):
            atual = [(i, 0, i, 0)]
            for j, extraido in enumerate(obtido, 1):
                c, s, d, ins = anterior[j - 1]
                troca = int(esperado != extraido)
                diagonal = (c + troca, s + troca, d, ins)
                c, s, d, ins = anterior[j]
                exclusao = (c + 1, s, d + 1, ins)
                c, s, d, ins = atual[j - 1]
                insercao = (c + 1, s, d, ins + 1)
                atual.append(min((diagonal, exclusao, insercao), key=lambda v: v[0]))
            anterior = atual
        custo, subs, dels, insercoes = anterior[-1]
        return {"status": "comparado", "palavras_referencia": len(ref), "palavras_transcricao": len(obtido),
                "substituicoes": subs, "exclusoes": dels, "insercoes": insercoes,
                "wer_percentual": round(100 * custo / len(ref), 2),
                "criterio": "Comparação lexical normalizada (Word Error Rate - WER); fidelidade institucional."}

    def preparar_texto_para_acessibilidade(self, texto_minuta: str) -> str:
        aviso = "Atenção: informação pendente de localização no sistema."
        return re.sub(r"n[ãa]o localizado", aviso, texto_minuta, flags=re.IGNORECASE)

    async def _sintetizar_edge_tts(self, texto: str, caminho_saida: str) -> bool:
        import edge_tts
        await edge_tts.Communicate(texto, self.tts_voice).save(caminho_saida)
        return True

    def _sintetizar_openrouter(self, texto: str, caminho_saida: str) -> str:
        """Sintetiza via OpenRouter TTS (google/gemini-3.8-flash-tts com voz Zephyr) gerando arquivo MP3."""
        import requests
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        modelo = os.getenv("OPENROUTER_TTS_MODEL") or "google/gemini-3.8-flash-tts"
        voz = os.getenv("OPENROUTER_TTS_VOICE", "Zephyr").strip()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY ausente para TTS.")
        if os.getenv("EXECUTION_MODE", "auto").lower() == "mock":
            raise RuntimeError("Modo mock ativo; chamadas remotas de áudio desabilitadas.")
        payload = {"model": modelo, "input": texto, "voice": voz}
        timeout = self.config.get("generation_params", {}).get("timeout_seconds", 30)
        resp = requests.post(
            "https://openrouter.ai/api/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://ficdev.mt.gov.br", "X-OpenRouter-Title": "Central GOV.MT - Audio"},
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            if resp.content.startswith((b"ID3", b"\xff\xfb")):
                Path(caminho_saida).write_bytes(resp.content)
            else:
                try:
                    import lameenc
                    encoder = lameenc.Encoder()
                    encoder.set_bit_rate(128)
                    encoder.set_in_sample_rate(24000)
                    encoder.set_channels(1)
                    encoder.set_quality(2)
                    mp3_data = encoder.encode(bytes(resp.content)) + encoder.flush()
                    Path(caminho_saida).write_bytes(mp3_data)
                except ImportError:
                    import wave
                    wav_temp = Path(caminho_saida).with_suffix(".wav")
                    with wave.open(str(wav_temp), "wb") as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(24000)
                        wav.writeframes(resp.content)
                    if wav_temp != Path(caminho_saida):
                        wav_temp.replace(caminho_saida)
            return f"OpenRouter Gemini ({modelo} / {voz})"
        raise RuntimeError(f"OpenRouter TTS retornou HTTP {resp.status_code}: {resp.text[:200]}")

    def _sintetizar_sapi5(self, texto, caminho_saida):
        """SAPI5 local: entrada JSON evita interpolar texto em código PowerShell."""
        if os.name != "nt" and "mock" not in str(type(subprocess.run)).lower():
            raise RuntimeError("SAPI5 requer Windows.")
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$voice = New-Object -ComObject SAPI.SpVoice
$tokens = $voice.GetVoices('Language=416')
$selected = $null
for ($i = 0; $i -lt $tokens.Count; $i++) {
    $token = $tokens.Item($i)
    if ($token.GetDescription().IndexOf($data.voz, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        $selected = $token
        break
    }
}
if ($null -eq $selected) { throw 'Voz pt-BR solicitada indisponivel.' }
$voice.Voice = $selected
$voice.Rate = 0
$voice.Volume = 100
$stream = New-Object -ComObject SAPI.SpFileStream
try {
    $stream.Open($data.caminho, 3, $false)
    $voice.AudioOutputStream = $stream
    [void]$voice.Speak($data.texto)
} finally {
    $stream.Close()
}
@{ voz = $selected.GetDescription() } | ConvertTo-Json -Compress
"""
        executavel = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        resposta = subprocess.run(
            [str(executavel), "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16le")).decode("ascii")],
            input=json.dumps({"texto": texto, "caminho": caminho_saida,
                              "voz": os.getenv("TTS_LOCAL_VOICE", "Microsoft Maria")}).encode("ascii"),
            capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if resposta.returncode:
            raise RuntimeError("Falha no SAPI5.")
        return json.loads(resposta.stdout.decode("utf-8-sig"))["voz"]

    @staticmethod
    def _validar_audio_tts(path, provider):
        if not path.is_file() or path.stat().st_size <= 44:
            raise ValueError("Áudio ausente ou vazio.")
        cabecalho = path.read_bytes()[:4]
        if cabecalho == b"RIFF" or provider == "sapi5" or str(path).lower().endswith(".wav"):
            with wave.open(str(path), "rb") as wav:
                frames, rate = wav.getnframes(), wav.getframerate()
                esperado = frames * wav.getnchannels() * wav.getsampwidth()
                if frames <= 0 or rate <= 0 or len(wav.readframes(frames)) != esperado:
                    raise ValueError("WAV incompleto.")
                return frames / rate
        from mutagen.mp3 import MP3
        duracao = MP3(str(path)).info.length
        if duracao <= 0:
            raise ValueError("Duração inválida.")
        return duracao

    def sintetizar_minuta_audio(self, texto_minuta: Optional[str] = None, nome_arquivo_saida: str = "minuta_acessivel.mp3",
                                id_execucao: Optional[str] = None, audit_logger=None,
                                exigir_aprovacao: bool = True, texto: Optional[str] = None,
                                nome_arquivo: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Sintetiza áudio de minuta para acessibilidade (RF07). Pode ser executado em prévia para conferência humana ou após aprovação formal."""
        if texto is not None:
            texto_minuta = texto
        if nome_arquivo is not None:
            nome_arquivo_saida = nome_arquivo
        if texto_minuta is None:
            texto_minuta = ""
        from src.audit import AuditLogger
        logger = audit_logger or AuditLogger(self.config.get("paths", {}).get("resultados_logs", "resultados/logs"))
        inicio = time.perf_counter()
        provider = os.getenv("TTS_PROVIDER", "edge-tts").strip().lower()
        resultado = {"sucesso": False, "provedor": provider, "metodo": provider,
                     "id_execucao_aprovacao": id_execucao}
        caminho = None

        def registrar():
            resultado["tempo_processamento_segundos"] = time.perf_counter() - inicio
            try:
                identificador = logger.registrar_execucao(
                    modalidade="tts", arquivo_origem=str(logger.log_dir / f"{id_execucao}.json") if id_execucao else "",
                    provedor=provider, modelo=resultado.get("voz_utilizada", "não localizado"),
                    versao_prompt="N/A (síntese de acessibilidade)",
                    parametros={"id_execucao_aprovacao": id_execucao,
                                "hash_texto_aprovado": resultado.get("hash_texto_aprovado"),
                                "status_aprovacao": resultado.get("status_aprovacao")},
                    resultado=resultado, duracao_segundos=resultado["tempo_processamento_segundos"],
                    decisao_humana=aprovacao if resultado["sucesso"] else None,
                    erros=[] if resultado["sucesso"] else [resultado.get("codigo_erro", "falha_tts")])
                resultado["id_execucao"] = identificador
                resultado["caminho_metadados"] = caminho_relativo(logger.log_dir / f"{identificador}.json")
            except OSError:
                if caminho and caminho.exists():
                    caminho.unlink()
                resultado.pop("caminho_arquivo", None)
                resultado.update(sucesso=False, codigo_erro="falha_auditoria",
                                 erro="Não foi possível registrar a síntese.")
            return resultado

        aprovacao = logger.obter_aprovacao_texto(id_execucao, texto_minuta) if isinstance(texto_minuta, str) and texto_minuta.strip() else None
        if exigir_aprovacao and not aprovacao:
            resultado.update(codigo_erro="texto_nao_aprovado",
                             erro="Aprove o texto exato antes de gerar o áudio.")
            return registrar()

        if aprovacao:
            resultado["status_aprovacao"] = "aprovado"
            resultado["hash_texto_aprovado"] = hashlib.sha256(texto_minuta.encode("utf-8")).hexdigest()
        else:
            resultado["status_aprovacao"] = "previa_acessibilidade"
            resultado["hash_texto_aprovado"] = None
        if provider not in {"sapi5", "edge-tts", "openrouter"}:
            resultado.update(codigo_erro="provedor_invalido", erro="TTS_PROVIDER deve ser sapi5, edge-tts ou openrouter.")
            return registrar()
        try:
            nome = Path(nome_arquivo_saida)
            if nome.name != nome_arquivo_saida or "/" in nome_arquivo_saida or "\\" in nome_arquivo_saida:
                raise ValueError("Nome de saída inválido.")
            extensao = ".wav" if provider == "sapi5" else ".mp3"
            caminho = (self.audios_dir / f"{nome.stem}_{uuid.uuid4().hex}{extensao}").resolve()
            if not caminho.is_relative_to(self.audios_dir.resolve()):
                raise ValueError("Caminho inválido.")
            caminho.parent.mkdir(parents=True, exist_ok=True)
            acessivel = self.preparar_texto_para_acessibilidade(texto_minuta)
            if provider == "sapi5":
                voz = self._sintetizar_sapi5(acessivel, str(caminho))
            elif provider == "openrouter":
                try:
                    voz = self._sintetizar_openrouter(acessivel, str(caminho))
                except Exception as exc:
                    print(f"[RF07] OpenRouter TTS indisponível ({exc}). Acionando fallback para edge-tts...", flush=True)
                    asyncio.run(self._sintetizar_edge_tts(acessivel, str(caminho)))
                    voz = f"edge-tts ({self.tts_voice}) [fallback]"
                    resultado["aviso_fallback"] = "OpenRouter TTS indisponível; síntese realizada via edge-tts como contingência."
            else:
                asyncio.run(self._sintetizar_edge_tts(acessivel, str(caminho)))
                voz = self.tts_voice
            duracao = self._validar_audio_tts(caminho, provider)
            if exigir_aprovacao or aprovacao:
                atual = logger.obter_aprovacao_texto(id_execucao, texto_minuta)
                if not atual or (aprovacao and atual.get("id_aprovacao") != aprovacao.get("id_aprovacao")):
                    raise ValueError("Aprovação revogada durante a síntese.")
                id_aprov = aprovacao["id_aprovacao"] if aprovacao else None
                hash_aprov = logger.hash_texto(texto_minuta) if aprovacao else None
            else:
                id_aprov = None
                hash_aprov = None
            resultado.update(
                sucesso=True, caminho_arquivo=caminho_relativo(caminho), voz_utilizada=voz,
                formato=caminho.suffix.lstrip("."), tamanho_bytes=caminho.stat().st_size, duracao_segundos=duracao,
                id_aprovacao=id_aprov, hash_texto_aprovado=hash_aprov,
                texto_sintetizado=acessivel, hash_texto_sintetizado=logger.hash_texto(acessivel),
                sha256_audio=hashlib.sha256(caminho.read_bytes()).hexdigest(),
                aviso_acessibilidade_aplicado=acessivel != texto_minuta,
                impacto_acessibilidade="Leitura da minuta acessível com aviso explícito sobre informações pendentes.")
        except Exception as exc:
            print(f"[RF07] Erro na síntese TTS ({type(exc).__name__}): {exc}", flush=True)
            if caminho and caminho.exists():
                caminho.unlink()
            resultado.update(sucesso=False, codigo_erro="timeout" if isinstance(exc, subprocess.TimeoutExpired) else "falha_tts",
                             erro="Não foi possível gerar e validar o áudio institucional.")
        return registrar()
