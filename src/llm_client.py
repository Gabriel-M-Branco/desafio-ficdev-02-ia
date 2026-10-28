"""
Cliente de Comunicação com Modelos de IA (RF04)
Hugging Face e OpenRouter opcional; falhas explícitas e extração heurística rastreável.
"""

import os
import json
import time
import re
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    duration_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Optional[float]
    status: str
    error_message: Optional[str] = None
    is_mock: bool = False
    finish_reason: Optional[str] = None
    provider_response_id: Optional[str] = None
    token_usage_source: str = "estimado"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


from src import resolver_caminho


class LLMClient:
    """
    Cliente para orquestração de LLMs com tratamento rigoroso de exceções,
    métricas de desempenho e custo não presumido.
    """

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.hf_token = os.getenv("HF_TOKEN", "").strip()
        # Suporta tanto OPENROUTER_API_KEY quanto OPENAI_API_KEY como alias multiuso
        self.openrouter_key = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        self.execution_mode = os.getenv("EXECUTION_MODE", "auto").lower()

        # Modelos configurados
        models_cfg = self.config.get("models", {})
        self.hf_model = models_cfg.get("llm_primary", "Qwen/Qwen2.5-72B-Instruct")
        self.text_provider = os.getenv("TEXT_PROVIDER", "openrouter" if self.openrouter_key else "huggingface").strip().lower()
        self.primary_model = (os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
                              if self.text_provider == "openrouter" else self.hf_model)
        self.fallback_model = models_cfg.get("llm_fallback", "meta-llama/Llama-3.3-70B-Instruct")

        # Parâmetros padrão
        gen_cfg = self.config.get("generation_params", {})
        self.default_temp = gen_cfg.get("temperature", 0.1)
        self.default_max_tokens = gen_cfg.get("max_tokens", 1500)
        self.default_timeout = int(os.getenv("LLM_TIMEOUT", gen_cfg.get("timeout_seconds", 60)))

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            p = resolver_caminho(config_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _estimate_tokens(self, text: str) -> int:
        """Estima o número de tokens com base na contagem de caracteres e palavras."""
        if not text:
            return 0
        return max(1, int(len(text) / 4))

    def _sanitize_log_message(self, message: str) -> str:
        """Garante que segredos ou tokens nunca sejam vazados em logs (RF04, RF11)."""
        clean = message
        if self.hf_token and len(self.hf_token) > 4:
            clean = clean.replace(self.hf_token, "[REDACTED_HF_TOKEN]")
        if self.openrouter_key and len(self.openrouter_key) > 4:
            clean = clean.replace(self.openrouter_key, "[REDACTED_OPENROUTER_KEY]")
        return clean

    def generate(self, prompt, system_instruction=None, model=None, temperature=None,
                 max_tokens=None, timeout=None, response_format=None) -> LLMResponse:
        """Somente provedores reais. Indisponibilidade nunca vira resposta fictícia."""
        inicio = time.perf_counter()
        modelo = model or self.primary_model
        temp = self.default_temp if temperature is None else temperature
        limite = self.default_max_tokens if max_tokens is None else max_tokens
        espera = self.default_timeout if timeout is None else timeout
        mensagens = ([{"role": "system", "content": system_instruction}] if system_instruction else [])
        mensagens.append({"role": "user", "content": prompt})

        import math
        def resposta(texto, provedor, modelo_efetivo, status="success", detalhe_erro=None, finish_reason=None, response_id=None, usage=None):
            entrada = self._estimate_tokens(prompt + (system_instruction or "")) if texto else 0
            saida = self._estimate_tokens(texto)
            fonte, custo = "estimado", None
            if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens")):
                entrada, saida, fonte = usage["prompt_tokens"], usage["completion_tokens"], "provedor"
                valor = usage.get("cost")
                if type(valor) in (int, float) and math.isfinite(valor) and valor >= 0:
                    custo = valor
            return LLMResponse(
                text=texto, model=modelo_efetivo, provider=provedor,
                duration_seconds=time.perf_counter()-inicio, prompt_tokens=entrada,
                completion_tokens=saida, total_tokens=entrada+saida, cost_usd=custo,
                status=status,
                error_message=detalhe_erro if detalhe_erro else (None if texto else "Geração indisponível; nenhum conteúdo simulado foi produzido."),
                is_mock=False,
                finish_reason=finish_reason,
                provider_response_id=response_id,
                token_usage_source=fonte,
            )

        def classificar(exc):
            codigo = getattr(getattr(exc, "response", None), "status_code", None)
            if codigo in (401, 403): return "auth_error"
            if codigo in (402,): return "billing_error"
            if codigo == 429: return "rate_limit_exceeded"
            if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower(): return "timeout"
            if isinstance(exc, ValueError): return "empty_or_invalid_response"
            return "service_unavailable"

        if self.execution_mode not in {"auto", "api"}:
            return resposta("", "none", modelo, "remote_disabled")

        if self.text_provider not in {"openrouter", "huggingface"}:
            return resposta("", "none", modelo, "invalid_provider")

        def chamar_hf():
            if not self.hf_token:
                return resposta("", "none", self.hf_model, "credentials_missing")
            from huggingface_hub import InferenceClient
            modelo_hf = (model if self.text_provider == "huggingface" else None) or self.hf_model
            cliente = InferenceClient(token=self.hf_token, timeout=espera)
            parametros = {"response_format": response_format} if response_format else {}
            dado = cliente.chat_completion(messages=mensagens, model=modelo_hf,
                                           temperature=temp, max_tokens=limite, **parametros)
            texto = dado.choices[0].message.content
            if not isinstance(texto, str) or not texto.strip():
                raise ValueError("Resposta HF vazia.")
            usage = {k: getattr(getattr(dado, "usage", None), k, None) for k in ("prompt_tokens", "completion_tokens")}
            return resposta(texto, "HuggingFace_Serverless", modelo_hf,
                            finish_reason=getattr(dado.choices[0], "finish_reason", None),
                            usage=usage)

        def chamar_openrouter():
            if not self.openrouter_key:
                return resposta("", "none", modelo, "credentials_missing")
            import requests
            modelo_or = (model if self.text_provider == "openrouter" else None) or os.getenv("OPENROUTER_MODEL", "openrouter/free")
            gratuito = modelo_or == "openrouter/free" or modelo_or.endswith(":free")
            if self.text_provider != "openrouter" and not gratuito:
                return resposta("", "none", modelo_or, "fallback_model_not_free")
            parametros = {"model": modelo_or, "messages": mensagens, "temperature": temp, "max_tokens": limite}
            if response_format:
                parametros.update(response_format=response_format, provider={"require_parameters": True})
            dado = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.openrouter_key}", "Content-Type": "application/json"},
                json=parametros,
                timeout=espera, allow_redirects=False
            )
            if dado.status_code != 200:
                erro = RuntimeError(f"OpenRouter HTTP {dado.status_code}")
                erro.response = dado
                raise erro
            corpo = dado.json()
            escolhas = corpo.get("choices") or [{}]
            texto = escolhas[0].get("message", {}).get("content")
            if not isinstance(texto, str) or not texto.strip():
                raise ValueError("Resposta OpenRouter vazia.")
            nome_provedor = "OpenRouter_Free" if gratuito else "OpenRouter"
            return resposta(texto, nome_provedor, corpo.get("model") or modelo_or,
                            finish_reason=escolhas[0].get("finish_reason"),
                            response_id=corpo.get("id"),
                            usage=corpo.get("usage"))

        provedores = [self.text_provider]
        if self.text_provider == "huggingface" and os.getenv("OPENROUTER_ENABLED", "false").lower() == "true":
            provedores.append("openrouter")
        if self.text_provider == "openrouter" and os.getenv("TEXT_FALLBACK_PROVIDER", "none").lower() == "huggingface":
            provedores.append("huggingface")

        for indice, provedor in enumerate(provedores):
            try:
                resultado = chamar_openrouter() if provedor == "openrouter" else chamar_hf()
            except Exception as exc:
                resultado = resposta("", provedor, modelo, classificar(exc))
            if resultado.status == "success":
                return resultado
            if indice + 1 < len(provedores):
                print(f"[Texto] {provedor} falhou ({resultado.status}); fallback explicitamente habilitado: {provedores[indice + 1]}.", flush=True)
        return resultado





    def _extrair_entidades_dinamico(self, texto: str, diag_seg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrai dinamicamente entidades estruturadas do texto fornecido, aplicando a regra
        estrita de alucinação zero ('não localizado' para qualquer campo não fornecido).
        """
        texto_busca = diag_seg.get("texto_limpo", texto)

        # 1. Protocolo
        m_proto = re.search(r"(?:Protocolo|Protocolo nº|Prot\.?)\s*[:=]?\s*([0-9]{4}[-/][0-9]{5,7})", texto_busca, re.IGNORECASE)
        if not m_proto:
            m_proto = re.search(r"\b(202\d[-/]\d{5,7})\b", texto_busca)
        protocolo = m_proto.group(1).strip() if m_proto else "não localizado"

        # 2. Data
        m_data_line = re.search(r"(?:^|[\r\n])\s*(?:Data|Emissão|Data da solicitação)\s*[:=][ \t]*([^\r\n,;]+)", texto_busca, re.IGNORECASE)
        if m_data_line:
            data = m_data_line.group(1).strip()
        else:
            data = "não localizado"

        # 3. Solicitante
        m_nome = re.search(r"(?:^|[\r\n])\s*(?:Solicitante|Nome completo|Nome do requerente|Nome do aluno|Requerente|Nome)\s*[:=][ \t]*([^\n\r,;]+)", texto_busca, re.IGNORECASE)
        if not m_nome:
            m_nome = re.search(r"(?:Meu nome é|Chamo-me|Eu sou)\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ'\s]+?)(?:\s+e\s+meu|\s+e\s+o|,|\.|\n|\r|$)", texto_busca, re.IGNORECASE)
        if not m_nome:
            m_nome = re.search(r"(?:^|[\r\n])\s*(?:Cidadão|Aluno)\s*[:=][ \t]*([^\n\r,;]+)", texto_busca, re.IGNORECASE)
        if not m_nome:
            m_nome = re.search(r"Atenciosamente,\s*\n+([A-ZÀ-ÿ][A-Za-zÀ-ÿ'\s]+?)(?:\n|\r|$)", texto_busca)
        solicitante = m_nome.group(1).strip() if m_nome else "não localizado"
        if solicitante != "não localizado":
            solicitante = re.sub(r"\s+", " ", solicitante).strip()

        # 4. CPF
        m_cpf = re.search(r"(?:CPF\s*[:=]?\s*)?(\d{3}\.\d{3}\.\d{3}-\d{2})\b", texto_busca)
        cpf = m_cpf.group(1).strip() if m_cpf else "não localizado"

        # 5. RG
        m_rg = re.search(r"(?:RG|Identidade)\s*[:=]?\s*([0-9.\-xX]{6,12})", texto_busca, re.IGNORECASE)
        rg = m_rg.group(1).strip() if m_rg else "não localizado"

        # 6. Órgão Expedidor
        m_exp = re.search(r"(?:Órgão Expedidor|Expedidor|SSP)\s*[:=]?\s*([A-Za-z/]{2,10})", texto_busca, re.IGNORECASE)
        orgao_expedidor = m_exp.group(1).strip() if m_exp else "não localizado"

        # 7. Data de Nascimento
        m_nasc = re.search(r"(?:Data de Nascimento|Nascimento|nasci em)\s*[:=]?\s*(\d{2}/\d{2}/\d{4})", texto_busca, re.IGNORECASE)
        data_nascimento = m_nasc.group(1).strip() if m_nasc else "não localizado"

        # 8. Naturalidade e UF
        m_nat = re.search(r"(?:Naturalidade\s*[:=]?\s*|nasci em \d{2}/\d{2}/\d{4},\s+em\s+)([A-Za-zÀ-ÿ]+)", texto_busca, re.IGNORECASE)
        naturalidade = m_nat.group(1).strip() if m_nat else "não localizado"

        m_uf = re.search(r"(?:UF|Estado)\s*[:=]?\s*([A-Z]{2})\b", texto_busca)
        uf = m_uf.group(1).strip() if m_uf else "não localizado"

        # 9. Filiação (Nome da Mãe e Pai)
        m_mae = re.search(r"(?:Nome da Mãe|mãe)\s*[,:=]?\s*([A-Za-zÀ-ÿ\s]+?)(?:;|\.|\n|\r|$)", texto_busca, re.IGNORECASE)
        nome_mae = m_mae.group(1).strip() if m_mae else "não localizado"
        if nome_mae.lower() in ("não localizado", "nao", ""):
            nome_mae = "não localizado"

        m_pai = re.search(r"(?:Nome do Pai|pai)\s*[,:=]?\s*([A-Za-zÀ-ÿ\s]+?)(?:;|\.|\n|\r|$)", texto_busca, re.IGNORECASE)
        nome_pai = m_pai.group(1).strip() if m_pai else "não localizado"
        if nome_pai.lower() in ("não localizado", "nao", ""):
            nome_pai = "não localizado"

        # 10. Curso
        m_curso = re.search(r"(?:curso|habilitação|vestibular para o curso de)\s*[:=]?\s+([A-Za-zÀ-ÿ\s]+?)(?:,|\.|\n|\r|;|$)", texto_busca, re.IGNORECASE)
        curso = m_curso.group(1).strip() if m_curso else "não localizado"
        if curso != "não localizado":
            curso = re.sub(r"(?i)^(de\s+|o\s+)", "", curso).strip()

        # 11. Eixo Tecnológico, Carga Horária, Turno, Início
        m_eixo = re.search(r"eixo(?:\s+tecnológico)?\s+([A-Za-zÀ-ÿ\s]+?)(?:,|\.|\n|\r|;|$)", texto_busca, re.IGNORECASE)
        eixo = m_eixo.group(1).strip() if m_eixo else "não localizado"

        m_ch = re.search(r"carga horária\s+(?:de\s+)?([0-9]+\s*(?:horas|h)?)", texto_busca, re.IGNORECASE)
        carga_horaria = m_ch.group(1).strip() if m_ch else "não localizado"

        m_turno = re.search(r"\b(noturno|matutino|vespertino|integral)\b", texto_busca, re.IGNORECASE)
        turno = m_turno.group(1).lower() if m_turno else "não localizado"

        m_ini = re.search(r"início\s+(?:em|previsto para)?\s*(\d{2}/\d{2}/\d{4})", texto_busca, re.IGNORECASE)
        inicio_curso = m_ini.group(1).strip() if m_ini else "não localizado"

        # 12. Contatos (E-mail e Telefone)
        m_email = re.search(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", texto_busca)
        email = m_email.group(1).strip() if m_email else "não localizado"

        m_tel = re.search(r"(?:Telefone|Celular|WhatsApp|Fone)\s*[:=]?\s*([0-9()\s.-]{8,20})", texto_busca, re.IGNORECASE)
        telefone = m_tel.group(1).strip() if m_tel else "não localizado"

        def campo(rotulo):
            match = re.search(r"(?:^|[\r\n])\s*" + rotulo + r"\s*:\s*([^\r\n]+)", texto_busca, re.IGNORECASE)
            return match.group(1).strip() if match else "não localizado"
        assunto = campo("Assunto")
        pedido = campo("Pedido")
        categoria = "Matrícula e Ingresso" if re.search(r"matr[ií]cula", texto_busca, re.IGNORECASE) else "Outros / Informações Gerais"

        extracao = {
            "protocolo": protocolo,
            "data": data,
            "solicitante": solicitante,
            "cpf": cpf,
            "rg": rg,
            "orgao_expedidor": orgao_expedidor,
            "data_nascimento": data_nascimento,
            "naturalidade": naturalidade,
            "uf": uf,
            "nome_mae": nome_mae,
            "nome_pai": nome_pai,
            "curso": curso,
            "eixo_tecnologico": eixo,
            "carga_horaria": carga_horaria,
            "turno": turno,
            "inicio_curso": inicio_curso,
            "email": email,
            "telefone": telefone,
            "assunto": assunto,
            "pedido": pedido,
            "categoria": categoria,
            "confianca": "não estimada",
            "necessidade_revisao_humana": True,
        }

        if diag_seg.get("detectada"):
            extracao["seguranca"] = {
                "tentativa_prompt_injection_detectada": True,
                "instrucao_maliciosa_ignorada": True,
                "nivel_risco": diag_seg.get("nivel_risco", "alto"),
                "observacao": diag_seg.get("observacao"),
            }

        return extracao

    def extrair_entidades_local(self, texto):
        """Extração regex real; não é geração de modelo nem substitui STT/OCR."""
        from src.prompts import SegurancaPrompts
        diagnostico = SegurancaPrompts.analisar_risco_injecao(texto)
        return self._extrair_entidades_dinamico(texto, diagnostico)
