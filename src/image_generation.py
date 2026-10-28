"""
Geração e Composição Visual Institucional Híbrida GOV.MT (RF10)
Geração de ilustração central temática + template institucional com brasão, cabeçalho e tarja de proveniência.
"""

import os
import json
import time
import uuid
import hashlib
import re
import base64
import io
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image, ImageDraw, ImageFont

from src import resolver_caminho, caminho_relativo
from src.llm_client import LLMClient


class ImageProviderError(RuntimeError):
    def __init__(self, mensagem, codigo="falha_geracao", response=None, codigos=None):
        super().__init__(mensagem)
        self.codigo_erro = codigo
        self.response = response
        self.codigos_provedor = codigos or []


class ImageGenerator:
    """
    Gerador de peças visuais híbridas (IA Generativa + Composição Programática Pillow).
    Aplica identidade institucional e proveniência; conformidade visual exige revisão humana.
    """

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.llm_client = LLMClient(config_path)
        image_config = self.config.get("image_generation", {})
        self.image_model = os.getenv("IMAGE_MODEL") or self.config.get("models", {}).get("image", "black-forest-labs/FLUX.1-schnell")
        self.image_provider = os.getenv("IMAGE_PROVIDER") or image_config.get("provider", "fal-ai")
        if self.image_provider == "cloudflare":
            self.image_model = os.getenv("CLOUDFLARE_IMAGE_MODEL") or "@cf/black-forest-labs/flux-1-schnell"
        elif self.image_provider == "openrouter":
            self.image_model = os.getenv("OPENROUTER_IMAGE_MODEL") or "google/gemini-3.1-flash-image"
        self.image_endpoint = os.getenv("IMAGE_ENDPOINT") or image_config.get("endpoint")
        if self.image_endpoint and self.image_provider != "cloudflare":
            url = urlsplit(self.image_endpoint)
            if (url.scheme not in {"http", "https"} or not url.netloc or url.username or
                    url.password or url.query or url.fragment):
                raise ValueError("Endpoint HTTP(S) sem credenciais na URL; use IMAGE_ENDPOINT_TOKEN.")
        self.image_params = {"width": 1024, "height": 1024, "num_inference_steps": 4,
                             "guidance_scale": 0.0, "seed": 42}
        self.image_params.update(image_config.get("parameters", {}))
        if os.getenv("IMAGE_SEED"):
            self.image_params["seed"] = int(os.environ["IMAGE_SEED"])
        self.image_timeout = image_config.get("timeout_seconds", 60)
        if self.image_provider == "cloudflare":
            # Não enviar parâmetros HF não documentados pelo endpoint Cloudflare.
            self.image_params = {"steps": self.image_params["num_inference_steps"]}
        self.output_dir = resolver_caminho(self.config.get("paths", {}).get("resultados_imagens", "resultados/imagens"))
        self.logo_path = resolver_caminho(self.config.get("paths", {}).get("logo_institucional", "dados/originais/brasao.png"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Paleta institucional GOV.MT
        gov_cores = self.config.get("gov_mt", {}).get("cores", {})
        self.cor_azul = gov_cores.get("azul", "#004A8F")
        self.cor_verde = gov_cores.get("verde", "#008B47")
        self.cor_amarelo = gov_cores.get("amarelo", "#F7B500")
        # A aprovação fica no manifesto/auditoria, vinculada ao hash dos pixels.
        # Tarja neutra evita modificar o arquivo depois de ele ser revisado.
        self.tarja_texto = "CONTEÚDO SINTÉTICO GERADO POR IA - Consulte o status de revisão"

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            p = resolver_caminho(config_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def construir_prompt_estruturado(self, titulo="COMUNICADO OFICIAL: MATRÍCULAS E INGRESSO ETEC 2026") -> Dict[str, str]:
        """
        Elabora o prompt estruturado com sujeito, composição, estilo, iluminação, proporção e restrições (RF10).
        """
        campos = {
            # Não enviar o título literal: ele pertence somente à composição Pillow.
            "contexto": "Illustration-only asset about technical education and student enrollment. All titles, subjects, institutional marks and captions will be added separately by software after generation",
            "sujeito": "A diverse group of fictional young adult students walking together in a welcoming technical school courtyard, carrying plain backpacks and closed notebooks with solid unmarked covers",
            "composicao": "Central students surrounded by simple geometric trees and plain campus architecture with unmarked facades. Open welcoming educational setting, abstract technology shapes, generous clean space, no reception counter or display surfaces",
            "estilo": "High-quality modern flat vector illustration for an official Brazilian public technical school enrollment announcement, harmonious palette of royal blue (#004A8F), emerald green (#008B47) and golden yellow (#F7B500)",
            "iluminacao": "Crisp vector shapes, balanced composition, soft lighting, professional and welcoming atmosphere",
            "proporcao": "Square 1:1 composition",
            "restricoes": "No text, no letters, no typography, no logos, no watermarks. No words, numbers, pseudo-writing, glyphs, labels, signs, signboards, plaques, banners, posters, billboards, school name signs, emblems or coats of arms anywhere. No writing on buildings, clothing, backpacks or notebooks. Do not draw a blank sign or any lettering surface. No medical coats, no stethoscopes, no clinical or hospital environment. Fictional people only",
        }
        # Uma única fonte: os campos salvos são exatamente os enviados ao modelo.
        return {**campos, "prompt_completo_en": ". ".join(campos.values())}

    def corrigir_placa_composicao(self, composicao, regiao, cor_fundo,
                                 texto="MATRÍCULAS E INGRESSO"):
        """Correção editorial explícita em pixels da composição, sem alterar a arte IA.

        Região (esquerda, topo, direita, base), com limites finais exclusivos.
        Não detecta placas nem aplica recortes de um documento a outras imagens.
        """
        x0, y0, x1, y1 = regiao
        if not (0 <= x0 < x1 <= composicao.width and 0 <= y0 < y1 <= composicao.height):
            raise ValueError("Região da placa fora da composição.")
        corrigida = composicao.copy()
        placa = Image.new(composicao.mode, (x1-x0, y1-y0), cor_fundo)
        draw = ImageDraw.Draw(placa)
        tamanho = 36
        fonte = self._fonte(tamanho)
        while draw.textlength(texto, font=fonte) > placa.width-32 and tamanho > 10:
            tamanho -= 1
            fonte = self._fonte(tamanho)
        limites = draw.textbbox((0, 0), texto, font=fonte)
        if limites[2]-limites[0] > placa.width-32 or limites[3]-limites[1] > placa.height-16:
            raise ValueError("Texto não cabe na placa.")
        xy = ((placa.width-(limites[2]-limites[0]))/2-limites[0],
              (placa.height-(limites[3]-limites[1]))/2-limites[1])
        draw.text(xy, texto, font=fonte, fill="#FFF2A8")
        corrigida.paste(placa, (x0, y0))
        return corrigida

    def _fonte(self, tamanho):
        """TrueType Unicode; nunca substitui silenciosamente por fonte bitmap."""
        candidatos = [os.getenv("IMAGE_FONT_PATH"),
                      str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"),
                      str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"),
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf"]
        for candidato in candidatos:
            if not candidato:
                continue
            try:
                fonte = ImageFont.truetype(candidato, tamanho)
                # Rejeita fontes sem os glifos portugueses exigidos pelo template.
                desconhecido = bytes(fonte.getmask("\ufffd"))
                if any(bytes(fonte.getmask(c)) == desconhecido for c in "áéíóúãõâêôçÁÉÍÓÚÃÕÂÊÔÇ"):
                    continue
                return fonte
            except (OSError, ValueError):
                continue
        raise RuntimeError("Fonte TrueType com suporte a português ausente; configure IMAGE_FONT_PATH.")

    def _texto(self, draw, posicao, texto, cor, tamanho, largura):
        fonte = self._fonte(tamanho)
        while draw.textlength(texto, font=fonte) > largura and tamanho > 10:
            tamanho -= 1
            fonte = self._fonte(tamanho)
        if draw.textlength(texto, font=fonte) > largura:
            raise ValueError("Texto excede o espaço do template institucional.")
        draw.text(posicao, texto, fill=cor, font=fonte)

    def _gerar_ilustracao_ia(self, prompt_en: str) -> Image.Image:
        """Geração real pelo provedor explícito; nenhum fallback gráfico."""
        token = os.getenv("HF_TOKEN", "").strip()
        if os.getenv("EXECUTION_MODE", "auto").lower() == "mock":
            raise RuntimeError("Geração de imagem desativada no modo mock.")
        if self.image_provider == "cloudflare":
            return self._gerar_cloudflare(prompt_en)
        if self.image_provider == "openrouter":
            return self._gerar_openrouter(prompt_en)
        if not token and not self.image_endpoint:
            raise RuntimeError("HF_TOKEN ausente.")
        if not self.image_provider or self.image_provider == "auto":
            raise ValueError("Selecione IMAGE_PROVIDER explícito para registrar o provedor efetivo.")
        from huggingface_hub import InferenceClient
        if self.image_endpoint:
            if not re.match(r"^https?://", self.image_endpoint):
                raise ValueError("IMAGE_ENDPOINT deve ser uma URL HTTP(S) compatível com HF.")
            # O SDK consulta tokens locais quando recebe string vazia; o cabeçalho
            # explícito impede que a credencial HF seja enviada ao servidor próprio.
            endpoint_token = os.getenv("IMAGE_ENDPOINT_TOKEN", "")
            client = InferenceClient(token=endpoint_token,
                                     headers={"authorization": f"Bearer {endpoint_token}" if endpoint_token else ""},
                                     provider="hf-inference", timeout=self.image_timeout)
        else:
            client = InferenceClient(token=token, provider=self.image_provider, timeout=self.image_timeout)
        imagem = client.text_to_image(prompt_en, model=self.image_endpoint or self.image_model, **self.image_params)
        if not isinstance(imagem, Image.Image) or min(imagem.size) <= 0:
            raise ValueError("Provedor não retornou uma imagem válida.")
        imagem.load()
        return imagem.convert("RGB")

    def _gerar_openrouter(self, prompt: str) -> Image.Image:
        """Geração de imagem central via modelos de difusão/visão do OpenRouter (ex: google/gemini-2.5-flash-image)."""
        import requests
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ImageProviderError("Configure OPENROUTER_API_KEY para geração de imagem.", "credencial_ausente")
        modelo = os.getenv("OPENROUTER_IMAGE_MODEL") or self.image_model or "google/gemini-2.5-flash-image"
        payload = {
            "model": modelo,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ficdev.mt.gov.br",
            "X-Title": "Central GOV.MT - Image Generation",
        }
        try:
            resposta = requests.post(url, headers=headers, json=payload, timeout=self.image_timeout)
        except requests.exceptions.Timeout as exc:
            raise ImageProviderError("Timeout ao conectar ao OpenRouter Imagem.", "timeout") from exc
        except Exception as exc:
            raise ImageProviderError(f"Falha de conexão com OpenRouter Imagem: {exc}", "indisponibilidade") from exc

        if resposta.status_code != 200:
            err_msg = ""
            try:
                err_msg = resposta.json().get("error", {}).get("message", "")
            except Exception:
                pass
            status = resposta.status_code
            if status in (401, 403):
                codigo = "autenticacao"
            elif status == 429:
                codigo = "limite_requisicoes"
            elif status == 402:
                codigo = "cobranca_ou_creditos"
            elif status >= 500:
                codigo = "indisponibilidade"
            else:
                codigo = "falha_geracao"
            raise ImageProviderError(f"OpenRouter Imagem HTTP {status}: {err_msg or 'requisição recusada'}", codigo, resposta)

        data = resposta.json()
        choices = data.get("choices", [])
        if not choices:
            raise ImageProviderError("OpenRouter não retornou escolhas de imagem.", "resposta_vazia")
        msg = choices[0].get("message", {})
        images = msg.get("images", [])
        b64_data = None
        if images and isinstance(images, list):
            url_img = images[0].get("image_url", {}).get("url", "")
            if "base64," in url_img:
                b64_data = url_img.split("base64,", 1)[1]
            elif url_img.startswith("http"):
                resp_img = requests.get(url_img, timeout=self.image_timeout)
                return Image.open(io.BytesIO(resp_img.content)).convert("RGB")
        if not b64_data:
            content = msg.get("content", "") or ""
            match = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
            if match:
                b64_data = match.group(1)
        if not b64_data:
            raise ImageProviderError("OpenRouter não retornou dados de imagem válidos.", "resposta_invalida")
        dados = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(dados))
        img.load()
        return img.convert("RGB")

    def _gerar_cloudflare(self, prompt):
        import requests
        conta = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if not conta or not token:
            raise ImageProviderError("Configure CLOUDFLARE_ACCOUNT_ID e CLOUDFLARE_API_TOKEN.", "credencial_ausente")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", conta):
            raise ImageProviderError("Account ID Cloudflare inválido.", "configuracao_invalida")
        if (not re.fullmatch(r"@[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", self.image_model)
                or ".." in self.image_model or not 1 <= self.image_params["steps"] <= 8):
            raise ImageProviderError("Modelo Cloudflare ou steps inválidos.", "configuracao_invalida")
        url = f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/run/{self.image_model}"
        resposta = requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"prompt": prompt, **self.image_params}, timeout=self.image_timeout, allow_redirects=False)
        tipo = resposta.headers.get("Content-Type", "").lower()
        corpo = None
        if "image/" not in tipo:
            try:
                corpo = resposta.json()
            except ValueError:
                pass
        falha_api = isinstance(corpo, dict) and corpo.get("success") is False
        if not 200 <= resposta.status_code < 300 or falha_api:
            erros = corpo.get("errors", []) if isinstance(corpo, dict) else []
            codigos = [str(e.get("code")) for e in erros if isinstance(e, dict)]
            mensagem = "; ".join(str(e.get("message", "")) for e in erros if isinstance(e, dict))
            status = resposta.status_code
            if "3036" in codigos:
                codigo = "cota_gratuita_esgotada"
            elif "3040" in codigos or status >= 500:
                codigo = "indisponibilidade"
            elif "5035" in codigos or status == 402:
                codigo = "cobranca_ou_creditos"
            elif status in (401, 403):
                codigo = "autenticacao"
            elif status == 429:
                codigo = "limite_requisicoes"
            elif status == 408 or "3007" in codigos:
                codigo = "timeout"
            else:
                codigo = "falha_geracao"
            raise ImageProviderError(f"Cloudflare HTTP {status}: {mensagem or 'requisição recusada'}", codigo, resposta, codigos)
        if tipo.startswith("image/"):
            dados = resposta.content
        else:
            resultado = corpo.get("result", corpo) if isinstance(corpo, dict) else None
            imagem = resultado.get("image") if isinstance(resultado, dict) else None
            if not isinstance(imagem, str) or not imagem.strip():
                raise ImageProviderError("Cloudflare não retornou imagem.", "resposta_vazia")
            if imagem.startswith("data:"):
                if "," not in imagem:
                    raise ImageProviderError("Data URI de imagem inválida.", "resposta_invalida")
                cabecalho, imagem = imagem.split(",", 1)
                if ";base64" not in cabecalho:
                    raise ImageProviderError("Data URI de imagem inválida.", "resposta_invalida")
            try:
                dados = base64.b64decode(re.sub(r"\s+", "", imagem), validate=True)
            except ValueError:
                raise ImageProviderError("Base64 inválido na resposta Cloudflare.", "resposta_invalida") from None
        try:
            with Image.open(io.BytesIO(dados)) as imagem:
                imagem.load()
                return imagem.convert("RGB")
        except (OSError, ValueError):
            raise ImageProviderError("Resposta Cloudflare não contém imagem decodificável.", "resposta_invalida") from None

    def _erro_seguro(self, exc):
        mensagem = self.llm_client._sanitize_log_message(str(exc))
        for chave in ("HF_TOKEN", "OPENROUTER_API_KEY", "IMAGE_ENDPOINT_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
            segredo = os.getenv(chave, "")
            if segredo:
                mensagem = mensagem.replace(segredo, "[REDACTED]")
        mensagem = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [REDACTED]", mensagem)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if getattr(exc, "codigo_erro", None):
            codigo = exc.codigo_erro
        elif status in (401, 403):
            codigo = "autenticacao"
        elif status == 402:
            codigo = "cobranca_ou_creditos"
        elif status == 429:
            codigo = "limite_requisicoes"
        elif "timeout" in type(exc).__name__.lower():
            codigo = "timeout"
        elif "connection" in type(exc).__name__.lower():
            codigo = "indisponibilidade"
        elif isinstance(exc, ImportError):
            codigo = "dependencia_ausente"
        else:
            codigo = "falha_geracao"
        return {"codigo": codigo, "tipo": type(exc).__name__, "status_http": status,
                "codigos_provedor": getattr(exc, "codigos_provedor", []),
                "mensagem": mensagem[:1000] or f"Falha no provedor de imagens ({codigo})."}

    def montar_template_institucional(
        self, ilustracao: Image.Image, titulo: str = "ORIENTAÇÃO SOBRE MATRÍCULAS E INGRESSO"
    ) -> Image.Image:
        """
        Monta o template oficial do GOV.MT com cabeçalho, brasão oficial, título, moldura e tarja de proveniência (RF10).
        """
        largura_total = 1080
        altura_total = 1350
        canvas = Image.new("RGB", (largura_total, altura_total), color="#FFFFFF")
        draw = ImageDraw.Draw(canvas)

        # 1. Barra de Topo Tricolor Oficial (Azul, Verde, Amarelo)
        draw.rectangle([0, 0, 360, 12], fill=self.cor_azul)
        draw.rectangle([360, 0, 720, 12], fill=self.cor_verde)
        draw.rectangle([720, 0, 1080, 12], fill=self.cor_amarelo)

        # 2. Cabeçalho Oficial com Brasão de Mato Grosso
        with Image.open(self.logo_path) as original:
            brasao = original.convert("RGBA")
        brasao.thumbnail((110, 110), Image.Resampling.LANCZOS)
        canvas.paste(brasao, (50, 35), brasao)

        # Textos institucionais do cabeçalho
        self._texto(draw, (180, 35), "GOVERNO DO ESTADO DE MATO GROSSO", "#004A8F", 24, 850)
        self._texto(draw, (180, 68), "SECRETARIA DE ESTADO DE CIÊNCIA, TECNOLOGIA E INOVAÇÃO", "#333333", 18, 850)
        self._texto(draw, (180, 95), "ESCOLA TÉCNICA ESTADUAL DE CUIABÁ - SECITECI/MT", "#666666", 16, 850)

        # Linha separadora institucional
        draw.line([40, 155, 1040, 155], fill="#DDDDDD", width=2)

        # 3. Título de Destaque da Comunicação
        draw.rounded_rectangle([40, 168, 1040, 235], radius=8, fill="#F4F8FC", outline="#004A8F", width=2)
        self._texto(draw, (60, 185), titulo, "#004A8F", 24, 960)

        # 4. Encaixe da Ilustração Central Gerada por IA (960 x 680)
        ilustracao_redim = ilustracao.resize((960, 680), Image.Resampling.LANCZOS)
        canvas.paste(ilustracao_redim, (60, 250))
        draw.rectangle([58, 248, 1022, 932], outline="#008B47", width=3)

        # 5. Painel de Orientações e Informações Relevantes ao Cidadão (RF10)
        draw.rounded_rectangle([40, 945, 1040, 1195], radius=8, fill="#F8FAFC", outline="#004A8F", width=2)
        draw.rounded_rectangle([40, 945, 1040, 985], radius=8, fill="#004A8F")
        draw.rectangle([40, 970, 1040, 985], fill="#004A8F")
        self._texto(draw, (60, 953), "INFORMAÇÕES E ORIENTAÇÕES IMPORTANTES AO ESTUDANTE", "#FFFFFF", 17, 940)

        self._texto(draw, (65, 1000), "• INÍCIO DAS AULAS: 01 de Fevereiro de 2027 | Turno: Noturno (Carga Horária: 1.200h)", "#1E293B", 17, 950)
        self._texto(draw, (65, 1038), "• DOCUMENTOS: Apresentar RG, CPF e Comprovante de Residência para validação definitiva", "#1E293B", 17, 950)
        self._texto(draw, (65, 1076), "• FREQUÊNCIA: Presença obrigatória nos 10 primeiros dias letivos para garantia da vaga", "#B91C1C", 17, 950)
        self._texto(draw, (65, 1114), "• ATENDIMENTO: Secretaria Escolar da ETEC Cuiabá | Portal: seciteci.mt.gov.br", "#004A8F", 17, 950)
        assunto = re.sub(r"^COMUNICADO OFICIAL:\s*", "", titulo, flags=re.IGNORECASE).strip()
        self._texto(draw, (60, 1152), f"ASSUNTO: {assunto}", self.cor_azul, 18, 960)

        # 6. Tarja Inferior Obrigatória de Proveniência (RF10 - Edital / AGENTS.md)
        altura_tarja = 140
        draw.rectangle([0, altura_total - altura_tarja, largura_total, altura_total], fill="#0A2540")
        draw.rectangle([0, altura_total - altura_tarja, largura_total, altura_total - altura_tarja + 6], fill=self.cor_amarelo)

        self._texto(draw,
            (50, altura_total - altura_tarja + 25),
            self.tarja_texto,
            "#FFFFFF", 21, 980,
        )
        self._texto(draw,
            (50, altura_total - altura_tarja + 62),
            "Comunicação institucional | Revisão humana obrigatória | ETEC/SECITECI/MT",
            "#A0C4E2", 16, 980,
        )
        self._texto(draw,
            (50, altura_total - altura_tarja + 92),
            f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Resolução: {largura_total}x{altura_total}",
            "#F7B500", 14, 980,
        )

        return canvas

    def gerar_comunicado_oficial(
        self,
        titulo: str = "COMUNICADO OFICIAL: MATRÍCULAS E INGRESSO ETEC 2026",
        nome_arquivo: str = "comunicado_institucional_govmt.png",
        audit_logger=None,
    ) -> Dict[str, Any]:
        """IA produz a arte; Pillow apenas compõe a peça. Erros são persistidos."""
        from src.audit import AuditLogger
        inicio = time.perf_counter()
        identificador = uuid.uuid4().hex
        prompt_info = self.construir_prompt_estruturado(titulo)
        metadados = {
            "identificador": identificador, "titulo": titulo, "sucesso": False,
            "data_geracao": datetime.now().astimezone().isoformat(),
            "modelo_ia_utilizado": self.image_model, "provedor_solicitado": self.image_provider,
            "provedor_efetivo": None, "ia_gerada": False,
            "estado_imagem": "nao_gerada", "endpoint": None if self.image_provider == "cloudflare" else self.image_endpoint,
            "parametros_geracao": dict(self.image_params), "timeout_seconds": self.image_timeout,
            "prompt_estruturado": prompt_info, "restricoes_aplicadas": prompt_info["restricoes"],
            "declaracao_proveniencia": self.tarja_texto, "status_revisao": "pendente_revisao",
            "custo_usd": None, "custo_status": "não informado pelo provedor",
            "template_institucional": "GOV.MT Oficial Padrão SECITECI",
            "conformidade_seguranca": {"sem_pessoas_reais": None, "sem_direitos_autorais_terceiros": None,
                                      "ilustracao_sem_texto_placas_logos": None,
                                      "tarja_visivel_aplicada": False, "revisao_humana_obrigatoria": True},
        }
        caminho_json = self.output_dir / f"falha_rf10_{identificador}.json"
        try:
            nome = Path(nome_arquivo)
            if nome.name != nome_arquivo or "/" in nome_arquivo or "\\" in nome_arquivo or nome.suffix.lower() != ".png":
                raise ValueError("Informe apenas um nome de arquivo PNG.")
            caminho_imagem = (self.output_dir / nome).resolve()
            if not caminho_imagem.is_relative_to(self.output_dir.resolve()):
                raise ValueError("Caminho de saída inválido.")
            # Preserva todos os artefatos existentes, inclusive os exemplos anteriores.
            if caminho_imagem.exists() or caminho_imagem.with_suffix(".json").exists() or caminho_imagem.with_name(caminho_imagem.stem + "_arte_ia.png").exists():
                caminho_imagem = caminho_imagem.with_name(f"{nome.stem}_{identificador}.png")
            caminho_json = caminho_imagem.with_suffix(".json")
            arte = self._gerar_ilustracao_ia(prompt_info["prompt_completo_en"])
            metadados.update(ia_gerada=True, estado_imagem="gerada",
                             provedor_efetivo="endpoint_hf_compativel" if self.image_endpoint and self.image_provider != "cloudflare" else self.image_provider)
            caminho_arte = caminho_imagem.with_name(caminho_imagem.stem + "_arte_ia.png")
            arte.save(str(caminho_arte), format="PNG")
            metadados.update(arquivo_arte_ia=caminho_relativo(caminho_arte),
                             dimensoes_arte=f"{arte.width}x{arte.height}",
                             sha256_arte_ia=hashlib.sha256(caminho_arte.read_bytes()).hexdigest())
            peca = self.montar_template_institucional(arte, titulo)
            fonte_path = Path(self._fonte(22).path)
            metadados["composicao"] = {
                "origem_textos": "Pillow / fonte TrueType Unicode; nunca renderizados pela IA",
                "titulo": titulo,
                "assunto": re.sub(r"^COMUNICADO OFICIAL:\s*", "", titulo, flags=re.IGNORECASE).strip(),
                "aviso_conteudo_sintetico": self.tarja_texto,
                "fonte": fonte_path.name,
                "sha256_fonte": hashlib.sha256(fonte_path.read_bytes()).hexdigest(),
                "brasao_origem": caminho_relativo(self.logo_path),
                "sha256_brasao": hashlib.sha256(self.logo_path.read_bytes()).hexdigest(),
                "adequacao_visual": "pendente_revisao_humana",
            }
            peca.save(str(caminho_imagem), format="PNG")
            metadados.update(sucesso=True, arquivo_imagem=caminho_relativo(caminho_imagem),
                             estado_imagem="pendente_revisao",
                             formato="PNG", dimensoes=f"{peca.width}x{peca.height}",
                             sha256_imagem=hashlib.sha256(caminho_imagem.read_bytes()).hexdigest())
            metadados["conformidade_seguranca"]["tarja_visivel_aplicada"] = True
        except Exception as exc:
            metadados.update(sucesso=False, erro=self._erro_seguro(exc))
        metadados["tempo_processamento_segundos"] = time.perf_counter() - inicio
        metadados["arquivo_metadados"] = caminho_relativo(caminho_json)
        try:
            caminho_json.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            metadados.update(sucesso=False, erro=self._erro_seguro(exc))
            metadados.pop("arquivo_metadados", None)
        resultado = {"sucesso": metadados["sucesso"], "metadados": metadados}
        if "arquivo_metadados" in metadados:
            resultado["caminho_metadados"] = metadados["arquivo_metadados"]
        try:
            logger = audit_logger or AuditLogger(self.config.get("paths", {}).get("resultados_logs", "resultados/logs"))
            resultado["id_execucao"] = logger.registrar_execucao(
                modalidade="imagem", arquivo_origem=str(self.logo_path),
                provedor=metadados["provedor_efetivo"] or self.image_provider, modelo=self.image_model,
                versao_prompt="Prompt Estruturado Institucional GOV.MT",
                parametros={"geracao": self.image_params, "prompt": prompt_info},
                resultado=metadados, duracao_segundos=metadados["tempo_processamento_segundos"],
                erros=[] if metadados["sucesso"] else [metadados["erro"]["codigo"]])
        except OSError:
            resultado.update(sucesso=False, codigo_erro="falha_auditoria", erro="Não foi possível registrar a geração.")
        if resultado["sucesso"]:
            resultado["caminho_imagem"] = metadados["arquivo_imagem"]
        else:
            resultado.setdefault("codigo_erro", metadados.get("erro", {}).get("codigo", "falha_geracao"))
            resultado.setdefault("erro", metadados.get("erro", {}).get("mensagem", "Falha na geração."))
        return resultado

    def revisar_imagem(self, id_execucao, hash_imagem, decisao, justificativa, operador, audit_logger=None,
                       identidade_autenticada=None):
        """Registra decisão humana sobre pixels exatos; não regenera nem altera a peça."""
        from src.audit import AuditLogger
        inicio = time.perf_counter()
        try:
            if (not re.fullmatch(r"[A-Za-z0-9_-]+", id_execucao) or decisao not in {"APROVADO", "REJEITADO"}
                    or not justificativa.strip() or not operador.strip()):
                raise ValueError("Identificador, decisão, justificativa e responsável são obrigatórios.")
            logger = audit_logger or AuditLogger(self.config.get("paths", {}).get("resultados_logs", "resultados/logs"))
            registro = json.loads((logger.log_dir / f"{id_execucao}.json").read_text(encoding="utf-8"))
            meta = registro["detalhes_completos"]
            if registro["modalidade"] != "imagem" or not meta.get("sucesso") or not meta.get("ia_gerada"):
                raise ValueError("A execução não comprova uma imagem gerada por IA.")
            imagem = resolver_caminho(meta["arquivo_imagem"])
            if (not imagem.resolve().is_relative_to(self.output_dir.resolve()) or
                    hash_imagem != meta["sha256_imagem"] or
                    hashlib.sha256(imagem.read_bytes()).hexdigest() != hash_imagem):
                raise ValueError("Imagem alterada ou hash divergente; revise o arquivo atual.")
            revisao = {"status": decisao, "operador": operador, "justificativa": justificativa,
                       "data_decisao": datetime.now().astimezone().isoformat(), "hash_imagem": hash_imagem}
            # Apenas o adaptador administrativo autenticado fornece este atributo.
            # Operador declarado e revisões antigas não autorizam publicação.
            if identidade_autenticada:
                revisao["identidade_autenticada"] = identidade_autenticada
            estado = "aprovada" if decisao == "APROVADO" else "rejeitada"
            meta = {**meta, "estado_imagem": estado, "status_revisao": estado,
                    "revisao_humana": revisao, "id_execucao_geracao": id_execucao}
            manifesto = self.output_dir / f"revisao_{uuid.uuid4().hex}.json"
            meta["arquivo_metadados"] = caminho_relativo(manifesto)
            manifesto.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            id_revisao = logger.registrar_execucao(
                modalidade="imagem_revisao", arquivo_origem=str(imagem), provedor=meta["provedor_efetivo"],
                modelo=meta["modelo_ia_utilizado"], versao_prompt="N/A (revisão humana)",
                parametros={"id_execucao_geracao": id_execucao, "hash_imagem": hash_imagem},
                resultado=meta, duracao_segundos=time.perf_counter() - inicio, decisao_humana=revisao)
            return {"sucesso": True, "id_execucao": id_revisao, "caminho_imagem": meta["arquivo_imagem"],
                    "caminho_metadados": caminho_relativo(manifesto), "metadados": meta}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return {"sucesso": False, "codigo_erro": "revisao_invalida", "erro": self._erro_seguro(exc)["mensagem"]}
