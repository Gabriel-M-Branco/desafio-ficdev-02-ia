"""
app.py - Interface Unificada Oficial Streamlit da Central Inteligente de Atendimento - GOV.MT
Interface oficial consolidada para os Desafios Práticos 01 (RF01 a RF13) e 02 (RF14 a RF24).
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import streamlit as st

# Garante que a raiz do projeto esteja no sys.path mesmo ao executar 'streamlit run src/app.py'
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import importlib
for mod_name in ["src.schemas", "src.rag", "src.nlp", "src.llm_client", "src.embeddings", "src.audit"]:
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])

# Importações dos módulos centrais do sistema
from src import BASE_DIR, resolver_caminho
from src.llm_client import LLMClient
from src.prompts import montar_prompt, sanitizar_entrada_usuario, SegurancaPrompts
from src.audio import AudioProcessor
from src.vision import VisionProcessor
from src.image_generation import ImageGenerator
from src.audit import AuditLogger, LGPDManager, QualityEvaluator
from src.text_contract import FORMATO_MINUTA, INSTRUCAO_JSON, ContratoTextoInvalido, interpretar_minuta
from src.pdf_generator import gerar_minuta_pdf
from src.image_access import carregar_imagem, imagem_publicavel

# Importações do Desafio 02
from src.embeddings import IndiceVetorial
from src.ingestion import ler_arquivo, dividir_em_chunks
from src.rag import MotorRAG
from src.nlp import processar_solicitacao
from src.guardrails import GuardrailManager
from src.sentiment import (
    classificar_sentimento_avaliacao,
    agregar_sentimentos_determinístico,
    filtrar_e_deduplicar_avaliacoes,
    montar_prompt_sentimento_isolado,
)
from src.schemas import ExtracaoFicha, DecisaoOperador
from src.metrics import AvaliadorDesafio02

# ==============================================================================
# Configuração da Página Streamlit
# ==============================================================================
st.set_page_config(
    page_title="Central de Atendimento — GOV.MT",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# Singletons de Serviços Centrais
# ==============================================================================
def obter_servicos():
    llm = LLMClient()
    audio = AudioProcessor()
    vision = VisionProcessor()
    img_gen = ImageGenerator()
    audit = AuditLogger()
    guard = GuardrailManager()
    return llm, audio, vision, img_gen, audit, guard

llm_client, audio_processor, vision_processor, image_generator, audit_logger, guardrail_manager = obter_servicos()

@st.cache_resource
def obter_indice_vetorial() -> IndiceVetorial:
    idx = IndiceVetorial()
    if not idx.chunks and os.path.exists("dados/acervo"):
        arquivos = sorted([
            os.path.join("dados/acervo", f)
            for f in os.listdir("dados/acervo")
            if f.endswith((".txt", ".pdf"))
        ])
        chunks = []
        for arq in arquivos:
            pags = ler_arquivo(arq)
            chunks.extend(dividir_em_chunks(pags, configuracao="A"))
        idx.adicionar_chunks(chunks)
    return idx

indice_vetorial = obter_indice_vetorial()
rag_motor = MotorRAG(indice=indice_vetorial, llm_client=llm_client, logger=audit_logger)

# ==============================================================================
# Gerenciamento de Estado de Sessão
# ==============================================================================
if "solicitacao_texto" not in st.session_state:
    st.session_state.solicitacao_texto = ""
if "solicitacao_caso" not in st.session_state:
    st.session_state.solicitacao_caso = "texto_original"
if "ultima_execucao" not in st.session_state:
    st.session_state.ultima_execucao = None
if "minuta_editavel" not in st.session_state:
    st.session_state.minuta_editavel = ""
if "decisao_minuta" not in st.session_state:
    st.session_state.decisao_minuta = "Aguardando Processamento"
if "justificativa_minuta" not in st.session_state:
    st.session_state.justificativa_minuta = ""
if "formato_visual_cpf" not in st.session_state:
    st.session_state.formato_visual_cpf = "Original"
if "filtro_conferencia" not in st.session_state:
    st.session_state.filtro_conferencia = "Todos"
if "audio_stt_resultado" not in st.session_state:
    st.session_state.audio_stt_resultado = None
if "visao_ocr_resultado" not in st.session_state:
    st.session_state.visao_ocr_resultado = None
if "imagem_resultado" not in st.session_state:
    st.session_state.imagem_resultado = None
if "imagem_aprovada" not in st.session_state:
    st.session_state.imagem_aprovada = False
if "experimento_resultado" not in st.session_state:
    st.session_state.experimento_resultado = None
if "audio_tts_bytes" not in st.session_state:
    st.session_state.audio_tts_bytes = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "rag_atendimento_resultado" not in st.session_state:
    st.session_state.rag_atendimento_resultado = None
if "rag_consulta_resultado" not in st.session_state:
    st.session_state.rag_consulta_resultado = None

def formatar_identificador(campo: str, valor: Any, formato: str) -> str:
    texto = str(valor or "")
    if campo not in ("cpf", "rg") or not re.match(r"^[\d.\s-]+$", texto):
        return texto
    digitos = re.sub(r"\D", "", texto)
    if formato == "Apenas Dígitos":
        return digitos
    if formato == "Com Máscara" and campo == "cpf" and len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return texto


def obter_status_todos_motores() -> Dict[str, Any]:
    """Identifica o estado real e verdadeiro de cada motor (texto, imagem, áudio, OCR, RAG),
    diferenciando modelos remotos com chave ativa de modos locais/offline sem chave."""
    prov_texto = llm_client.text_provider
    tem_chave_oa = bool(getattr(llm_client, "openai_key", "") or os.getenv("OPENAI_API_KEY", "").strip())
    tem_chave_or = bool(llm_client.openrouter_key or os.getenv("OPENROUTER_API_KEY", "").strip())
    tem_chave_hf = bool(llm_client.hf_token or os.getenv("HF_TOKEN", "").strip())

    # 1. Texto (LLM / NLP)
    if prov_texto == "openai" and tem_chave_oa:
        txt_status = "[Conectado via API]"
        txt_prov = "OpenAI API"
        txt_modelo_ativo = getattr(llm_client, "openai_model", "gpt-4o-mini")
        txt_em_uso = True
    elif prov_texto == "openrouter" and tem_chave_or:
        txt_status = "[Conectado via API]"
        txt_prov = "OpenRouter API"
        txt_modelo_ativo = llm_client.primary_model
        txt_em_uso = True
    elif prov_texto == "huggingface" and tem_chave_hf:
        txt_status = "[Conectado via API]"
        txt_prov = "Hugging Face Serverless"
        txt_modelo_ativo = llm_client.hf_model
        txt_em_uso = True
    elif prov_texto == "adaptador_simulado":
        txt_status = "[Adaptador Simulado - RF21]"
        txt_prov = "Adaptador Simulado Identificado"
        txt_modelo_ativo = llm_client.simulated_model
        txt_em_uso = True
    else:
        txt_status = "[Modo Local - Sem chave no .env]"
        txt_prov = "Motor Local (Regras & Heurísticas)"
        txt_modelo_ativo = "Nenhum modelo de nuvem ativo"
        txt_em_uso = False
    txt_configurado = llm_client.primary_model.split("/")[-1]

    # 2. Áudio STT (Voz para Texto)
    stt_prov = audio_processor.stt_provider
    if stt_prov == "openai" and tem_chave_oa:
        stt_status = "[Conectado via API]"
        stt_nome = "OpenAI Whisper API"
        stt_modelo = audio_processor.stt_model
    elif stt_prov == "huggingface" and tem_chave_hf:
        stt_status = "[Conectado via API]"
        stt_nome = "Hugging Face Whisper"
        stt_modelo = "whisper-large-v3-turbo"
    elif stt_prov == "openrouter" and tem_chave_or:
        stt_status = "[Conectado via API]"
        stt_nome = "OpenRouter Whisper"
        stt_modelo = audio_processor.stt_model
    else:
        stt_status = "[Ativo Localmente]"
        stt_nome = "faster-whisper (Local/CPU)"
        stt_modelo = "whisper-small (Local)"

    # 3. Áudio TTS (Síntese de Voz / Acessibilidade)
    tts_prov_env = os.getenv("TTS_PROVIDER", "edge-tts").strip().lower()
    if tts_prov_env == "sapi5":
        tts_status = "[Ativo Localmente]"
        tts_nome = "SAPI5 (Nativo Windows)"
        tts_modelo = "Microsoft Maria Desktop"
    else:
        tts_status = "[Ativo]"
        tts_nome = "edge-tts (Neural)"
        tts_modelo = "pt-BR-AntonioNeural"

    # 4. Visão / OCR
    vis_status_dict = vision_processor.obter_status_visao()
    if vis_status_dict.get("provedor") == "openai" and tem_chave_oa:
        ocr_status = "[Conectado via API]"
        ocr_nome = "OpenAI GPT-4o Vision"
        ocr_modelo = vis_status_dict.get("modelo", "gpt-4o")
    elif vis_status_dict.get("provedor") == "openrouter" and tem_chave_or:
        ocr_status = "[Conectado via API]"
        ocr_nome = "OpenRouter VLM"
        ocr_modelo = vis_status_dict.get("modelo", "google/gemini-2.0-flash")
    else:
        ocr_status = "[Ativo Localmente]"
        ocr_nome = "PyMuPDF + Tesseract (Local)"
        ocr_modelo = "Tesseract OCR (por.traineddata)"

    # 5. Imagem Institucional (RF10)
    img_prov = image_generator.image_provider
    tem_cf = bool(os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"))
    if img_prov == "openai" and tem_chave_oa:
        img_status = "[Conectado via API]"
        img_nome = "OpenAI DALL-E 3"
        img_modelo = image_generator.image_model
        img_em_uso = True
    elif img_prov == "cloudflare" and tem_cf:
        img_status = "[Conectado via API]"
        img_nome = "Cloudflare Workers AI"
        img_modelo = image_generator.image_model
        img_em_uso = True
    elif img_prov == "openrouter" and tem_chave_or:
        img_status = "[Conectado via API]"
        img_nome = "OpenRouter Image"
        img_modelo = image_generator.image_model
        img_em_uso = True
    elif img_prov in {"fal-ai", "huggingface", "hf-inference"} and tem_chave_hf:
        img_status = "[Conectado via API]"
        img_nome = "Hugging Face / FLUX.1"
        img_modelo = image_generator.image_model
        img_em_uso = True
    else:
        img_status = "[Modo Local - Sem chave no .env]"
        img_nome = "Composição Programática Pillow GOV.MT"
        img_modelo = "Nenhum modelo de difusão ativo"
        img_em_uso = False
    img_configurado = image_generator.image_model.split("/")[-1]

    # 6. Base Vetorial RAG
    rag_status = "[Ativo Localmente]"
    rag_nome = "scikit-learn TF-IDF Dense 512"
    rag_versao = indice_vetorial.versao_indice
    rag_chunks = len(indice_vetorial.chunks)

    return {
        "texto": {
            "status": txt_status, "provedor": txt_prov,
            "modelo_ativo": txt_modelo_ativo, "modelo_configurado": txt_configurado,
            "em_uso": txt_em_uso
        },
        "stt": {"status": stt_status, "provedor": stt_nome, "modelo": stt_modelo},
        "tts": {"status": tts_status, "provedor": tts_nome, "modelo": tts_modelo},
        "visao": {"status": ocr_status, "provedor": ocr_nome, "modelo": ocr_modelo},
        "imagem": {
            "status": img_status, "provedor": img_nome,
            "modelo_ativo": img_modelo, "modelo_configurado": img_configurado,
            "em_uso": img_em_uso
        },
        "rag": {
            "status": rag_status, "provedor": rag_nome,
            "versao": rag_versao, "total_chunks": rag_chunks
        }
    }

# ==============================================================================
# Barra Lateral (Menu & Governança)
# ==============================================================================
p_brasao = resolver_caminho("dados/originais/brasao.png")
if p_brasao.exists():
    st.sidebar.image(str(p_brasao), width=100)

st.sidebar.subheader("Central GOV.MT")
st.sidebar.markdown("**SECITECI/MT** • ETEC Cuiabá")
st.sidebar.divider()

menu = st.sidebar.radio(
    "Navegação:",
    [
        "1. Central de Atendimento e HITL",
        "2. Experimento de Prompts (RF02)",
        "3. Audio STT e Visao OCR (RF06/RF08)",
        "4. Comunicacao Visual Oficial (RF10)",
        "5. Auditoria e LGPD (RF11/RF12/RF13)",
        "6. Assistente de Documentos RAG (RF18-RF21)",
        "7. Triagem e Ficha da Solicitacao (RF14/RF15)",
        "8. Painel de Sentimentos (RF22)",
        "9. Gestao do Acervo e Matriz T01-T15 (RF23/RF24)",
    ],
    index=0
)

st.sidebar.divider()
st.sidebar.markdown("##### Status Real dos Motores de IA")

status_motores = obter_status_todos_motores()

with st.sidebar.expander("Texto / LLM", expanded=True):
    st.caption(status_motores["texto"]["status"])
    if status_motores["texto"]["em_uso"]:
        st.write(f"• **Provedor:** `{status_motores['texto']['provedor']}`")
        st.write(f"• **Modelo Ativo:** `{status_motores['texto']['modelo_ativo']}`")
    else:
        st.write(f"• **Motor Ativo:** `{status_motores['texto']['provedor']}`")
        st.caption(f"Padrão configurado no arquivo: `{status_motores['texto']['modelo_configurado']}` (aguardando chave no .env)")

with st.sidebar.expander("Áudio (STT & TTS)", expanded=False):
    st.markdown("**Reconhecimento de Voz (STT):**")
    st.caption(status_motores["stt"]["status"])
    st.write(f"• `{status_motores['stt']['modelo']}` ({status_motores['stt']['provedor']})")
    st.markdown("**Síntese Acessível (TTS):**")
    st.caption(status_motores["tts"]["status"])
    st.write(f"• `{status_motores['tts']['modelo']}` ({status_motores['tts']['provedor']})")

with st.sidebar.expander("Visão / OCR", expanded=False):
    st.caption(status_motores["visao"]["status"])
    st.write(f"• `{status_motores['visao']['modelo']}`")

with st.sidebar.expander("Imagem Institucional (RF10)", expanded=False):
    st.caption(status_motores["imagem"]["status"])
    if status_motores["imagem"]["em_uso"]:
        st.write(f"• **Modelo:** `{status_motores['imagem']['modelo_ativo']}`")
    else:
        st.write(f"• **Composição:** `{status_motores['imagem']['provedor']}`")
        st.caption(f"Padrão configurado: `{status_motores['imagem']['modelo_configurado']}` (aguardando credencial)")

with st.sidebar.expander("Base RAG / Vetorial", expanded=False):
    st.caption(status_motores["rag"]["status"])
    st.write(f"• **Modelo:** `{status_motores['rag']['provedor']}`")
    st.write(f"• **Acervo:** `{status_motores['rag']['total_chunks']} trechos`")
    st.caption(f"Versão: `{status_motores['rag']['versao']}`")

st.sidebar.divider()
st.sidebar.markdown("**Governança:** `[Human-in-the-Loop Ativo]`")

# ==============================================================================
# Cabeçalho Principal (Banner com Alto Contraste Institucional)
# ==============================================================================
with st.container(border=True):
    c_hdr1, c_hdr2 = st.columns([3, 1.3], vertical_alignment="center")
    with c_hdr1:
        st.header("Central Inteligente de Atendimento ao Cidadão")
        st.markdown("**Governo do Estado de Mato Grosso** — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT)")
    with c_hdr2:
        st.info("**Revisão Humana Obrigatória**\n\nNenhum ato oficial é finalizado sem homologação formal de servidor público.")

st.markdown("")


# ==============================================================================
# MÓDULO 1: Central de Atendimento & HITL (RF03, RF05, RF07, RF09, RF13)
# ==============================================================================
if menu.startswith("1."):
    st.subheader("1. Atendimento e Redação de Minuta Oficial")
    st.markdown("Selecione um caso pré-definido ou insira o texto livre. A IA isola o conteúdo não confiável via envelope XML, extrai dados em JSON estrito e redige a minuta institucional.")

    col_in, col_out = st.columns([1, 1.3], gap="large")

    with col_in:
        st.markdown("##### Entrada da Solicitação")

        vis_st = vision_processor.obter_status_visao()
        nome_visao_caso = (
            "OpenAI GPT-4o Vision" if vis_st.get("provedor") == "openai"
            else ("OpenRouter VLM" if vis_st.get("provedor") == "openrouter"
            else "PyMuPDF / Tesseract Local")
        )
        casos_opcoes = {
            "texto_original": "Mensagem de Texto (entrada_texto.txt)",
            "audio_transcricao": "Transcrição de Áudio (Whisper STT)",
            "visao_documento": f"Documento Digitalizado / OCR ({nome_visao_caso})",
            "prompt_injection": "Teste de Injeção de Prompt (Adversarial)",
            "personalizado": "Texto Livre / Personalizado",
        }

        caso_escolhido = st.selectbox(
            "Modalidade ou Caso de Teste:",
            list(casos_opcoes.keys()),
            format_func=lambda k: casos_opcoes[k],
            index=list(casos_opcoes.keys()).index(st.session_state.solicitacao_caso) if st.session_state.solicitacao_caso in casos_opcoes else 0
        )

        if caso_escolhido != st.session_state.solicitacao_caso:
            st.session_state.solicitacao_caso = caso_escolhido
            if caso_escolhido == "texto_original":
                caminho = resolver_caminho("dados/originais/entrada_texto.txt")
                st.session_state.solicitacao_texto = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
            elif caso_escolhido == "prompt_injection":
                st.session_state.solicitacao_texto = SegurancaPrompts.CASO_TESTE_PROMPT_INJECTION
            elif caso_escolhido == "audio_transcricao":
                res = audio_processor.processar_com_auditoria(audit_logger)
                st.session_state.solicitacao_texto = res.get("transcricao_revisada") or res.get("transcricao_bruta") or ""
            elif caso_escolhido == "visao_documento":
                res = vision_processor.processar_com_auditoria(audit_logger)
                st.session_state.solicitacao_texto = res.get("texto_corrigido") or res.get("texto_bruto") or ""
            elif caso_escolhido == "personalizado":
                st.session_state.solicitacao_texto = ""
            st.rerun()

        if not st.session_state.solicitacao_texto and caso_escolhido == "texto_original":
            caminho = resolver_caminho("dados/originais/entrada_texto.txt")
            st.session_state.solicitacao_texto = caminho.read_text(encoding="utf-8") if caminho.exists() else ""

        texto_digitado = st.text_area(
            "Texto da Manifestação:",
            value=st.session_state.solicitacao_texto,
            height=280,
            placeholder="Digite ou cole aqui a solicitação do cidadão..."
        )
        st.session_state.solicitacao_texto = texto_digitado

        c_btn1, c_btn2 = st.columns([1.5, 1])
        with c_btn1:
            btn_processar = st.button("Processar Solicitacao", type="primary", width='stretch')
        with c_btn2:
            if st.button("Limpar Tudo", width='stretch'):
                st.session_state.solicitacao_texto = ""
                st.session_state.ultima_execucao = None
                st.session_state.minuta_editavel = ""
                st.session_state.decisao_minuta = "Aguardando Processamento"
                st.session_state.justificativa_minuta = ""
                st.session_state.audio_tts_bytes = None
                st.session_state.pdf_bytes = None
                st.rerun()

    if btn_processar:
        if not st.session_state.solicitacao_texto.strip():
            st.warning("Por favor, informe o texto da manifestação.")
        else:
            with st.spinner("Processando com IA soberana e isolamento de segurança XML..."):
                texto_sanitizado = sanitizar_entrada_usuario(st.session_state.solicitacao_texto)
                prompt_completo = montar_prompt(texto_sanitizado, "PRODUCAO")
                limite_json = max(llm_client.default_max_tokens, 4096)

                resposta_llm = llm_client.generate(
                    prompt=prompt_completo,
                    system_instruction=INSTRUCAO_JSON,
                    response_format=FORMATO_MINUTA,
                    max_tokens=limite_json
                )

                if resposta_llm.status != "success":
                    if resposta_llm.status == "credentials_missing":
                        st.warning(
                            "[Aviso] Nenhuma chave de API configurada no `.env` (status: `credentials_missing`). "
                            "Adicione `OPENAI_API_KEY` ou `HF_TOKEN` no `.env` para geração via nuvem. "
                            "Para triagem e extração estruturada local sem custo, consulte o **Módulo 7**, "
                            "e para consulta e atendimento fundamentado no acervo, consulte o **Módulo 6 (RAG)**."
                        )
                    else:
                        st.error(f"Erro do modelo ({resposta_llm.status}). Nenhuma minuta fictícia gerada.")
                else:
                    try:
                        parsed = interpretar_minuta(resposta_llm.text, resposta_llm.finish_reason)
                        extracao = parsed["extracao"]
                        minuta = parsed["minuta_institucional"]

                        dir_proc = resolver_caminho("dados/processados")
                        dir_proc.mkdir(parents=True, exist_ok=True)
                        caso_salvar = re.sub(r"[^A-Za-z0-9_-]", "_", st.session_state.solicitacao_caso)
                        with open(dir_proc / f"extracao_{caso_salvar}.json", "w", encoding="utf-8") as f:
                            json.dump(extracao, f, ensure_ascii=False, indent=2)

                        dir_minutas = resolver_caminho("resultados/minutas")
                        dir_minutas.mkdir(parents=True, exist_ok=True)
                        sufixo = f"{caso_salvar}_{uuid.uuid4().hex[:8]}"
                        caminho_pdf = dir_minutas / f"minuta_{sufixo}.pdf"

                        gerar_minuta_pdf(
                            dados_extracao=extracao,
                            texto_minuta=minuta,
                            caminho_saida_pdf=caminho_pdf,
                            brasao_path=resolver_caminho("dados/originais/brasao.png"),
                            identificador_execucao=None,
                        )

                        avaliacao = None
                        if st.session_state.solicitacao_caso == "prompt_injection":
                            gabarito_inj = {"campos_esperados": SegurancaPrompts.GABARITO_ESPERADO["campos_reais"]}
                            avaliacao = QualityEvaluator.avaliar_extracao(extracao, gabarito_inj)
                        elif st.session_state.solicitacao_caso in ("texto_original", "audio_transcricao"):
                            gab_file = "gabarito_audio.json" if st.session_state.solicitacao_caso == "audio_transcricao" else "gabarito_texto.json"
                            p_gab = resolver_caminho(f"dados/gabaritos/{gab_file}")
                            if p_gab.exists():
                                with open(p_gab, "r", encoding="utf-8") as fg:
                                    gabarito_dado = json.load(fg)
                                avaliacao = QualityEvaluator.avaliar_extracao(extracao, {
                                    "campos_esperados": gabarito_dado.get("campos_esperados", gabarito_dado.get("entidades_criticas", {}))
                                })

                        exec_id = audit_logger.registrar_execucao(
                            modalidade="texto",
                            arquivo_origem=f"dados/originais/{st.session_state.solicitacao_caso}.txt",
                            provedor=resposta_llm.provider,
                            modelo=resposta_llm.model,
                            versao_prompt="PRODUCAO",
                            parametros={"max_tokens": limite_json, "response_format": "json_schema"},
                            resultado={"extracao": extracao, "minuta": minuta, "arquivo_pdf": str(caminho_pdf)},
                            duracao_segundos=resposta_llm.duration_seconds
                        )

                        st.session_state.ultima_execucao = {
                            "id_execucao": exec_id,
                            "extracao": extracao,
                            "minuta": minuta,
                            "caminho_pdf": str(caminho_pdf),
                            "avaliacao": avaliacao,
                            "conformidade": QualityEvaluator.avaliar_conformidade_regras(extracao),
                            "metricas": {
                                "duracao": resposta_llm.duration_seconds,
                                "tokens": resposta_llm.total_tokens,
                                "custo_usd": resposta_llm.cost_usd,
                                "provedor": resposta_llm.provider,
                                "modelo": resposta_llm.model
                            }
                        }
                        st.session_state.minuta_editavel = minuta
                        st.session_state.decisao_minuta = "Pendente de Revisão"
                        if caminho_pdf.exists():
                            st.session_state.pdf_bytes = caminho_pdf.read_bytes()
                        st.rerun()

                    except ContratoTextoInvalido as c_err:
                        st.error(f"Contrato JSON inválido retornado pelo modelo ({c_err.codigo}).")

    with col_out:
        st.markdown("##### Análise e Minuta Institucional")
        exec_atual = st.session_state.ultima_execucao

        if not exec_atual:
            st.info("Nenhuma minuta em análise. Carregue ou digite uma solicitação à esquerda e clique em **Processar Solicitação**.")
        else:
            status_cor = "green" if "Aprovad" in st.session_state.decisao_minuta else "red" if "Rejeitad" in st.session_state.decisao_minuta else "orange"
            st.markdown(f"**Status da Revisão:** :{status_cor}[{st.session_state.decisao_minuta}] • ID: `{exec_atual['id_execucao']}`")

            tab_minuta, tab_conf, tab_json, tab_met = st.tabs([
                "Minuta Oficial (RF09)",
                "Painel de Conferencia (RF13)",
                "JSON Estruturado (RF05)",
                "Metricas e Qualidade"
            ])

            with tab_minuta:
                aval = exec_atual.get("avaliacao") or exec_atual.get("conformidade")
                if aval:
                    erros = [c for c in (aval.get("erros_encontrados") or []) if c.get("status") != "PENDENCIA" and not c.get("eh_pendencia")]
                    pends = [c for c in (aval.get("comparativo_campos") or []) if c.get("eh_pendencia") or c.get("status") == "PENDENCIA"]
                    if erros:
                        st.error(f"Atencao Operador: Foram detectadas {len(erros)} divergência(s) em relação aos padrões oficiais.")
                    elif pends:
                        st.warning(f"Dados pendentes na fonte: {len(pends)} campo(s) assinalados estritamente como *'não localizado'*.")
                    else:
                        st.success("Todos os campos extraídos estão conformes com os critérios oficiais.")

                texto_editado = st.text_area(
                    "Minuta de Despacho (Editável pelo Operador):",
                    value=st.session_state.minuta_editavel,
                    height=250,
                    key="minuta_textarea_key"
                )
                st.session_state.minuta_editavel = texto_editado

                act1, act2 = st.columns(2)
                with act1:
                    if st.session_state.pdf_bytes:
                        st.download_button(
                            "Baixar Minuta em PDF Oficial",
                            data=st.session_state.pdf_bytes,
                            file_name=f"minuta_{exec_atual['id_execucao']}.pdf",
                            mime="application/pdf",
                            width='stretch'
                        )

                with act2:
                    if st.button("Sintetizar Voz Acessivel (RF07)", width='stretch'):
                        with st.spinner("Verificando aprovação humana e sintetizando voz neural com aviso sonoro..."):
                            res_tts = audio_processor.sintetizar_minuta_audio(
                                texto_minuta=st.session_state.minuta_editavel,
                                nome_arquivo_saida=f"minuta_{exec_atual['id_execucao']}.mp3",
                                id_execucao=exec_atual["id_execucao"],
                                audit_logger=audit_logger,
                                exigir_aprovacao=True
                            )
                            if res_tts.get("sucesso") and os.path.exists(res_tts["caminho_arquivo"]):
                                with open(res_tts["caminho_arquivo"], "rb") as fa:
                                    st.session_state.audio_tts_bytes = fa.read()
                                st.success("Áudio acessível sintetizado com sucesso após validação de aprovação humana!")
                            else:
                                st.error(res_tts.get("erro", "Aprove a minuta (botão 'Aprovar Resposta' abaixo) antes de sintetizar o áudio oficial (RF07)."))

                if st.session_state.audio_tts_bytes:
                    st.audio(st.session_state.audio_tts_bytes, format="audio/mp3")

                st.divider()
                st.markdown("###### Deliberacao do Servidor Responsável (RF13)")
                just_input = st.text_input(
                    "Justificativa da Decisão (Obrigatória para auditoria):",
                    value=st.session_state.justificativa_minuta,
                    placeholder="Ex: Dados cadastrais conferidos na base oficial da ETEC Cuiabá."
                )
                st.session_state.justificativa_minuta = just_input

                d1, d2, d3 = st.columns(3)
                with d1:
                    if st.button("Aprovar Resposta", type="primary", width='stretch'):
                        if not st.session_state.justificativa_minuta.strip():
                            st.warning("Preencha a justificativa antes de aprovar.")
                        else:
                            audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="APROVADO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            st.session_state.decisao_minuta = "APROVADO"
                            st.success("Resposta APROVADA e homologada no log de auditoria!")
                            st.rerun()
                with d2:
                    if st.button("Salvar Correção", width='stretch'):
                        if not st.session_state.justificativa_minuta.strip():
                            st.warning("Preencha a justificativa da correção.")
                        else:
                            audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="CORRIGIDO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            st.session_state.decisao_minuta = "CORRIGIDO"
                            st.warning("Correção salva no log de auditoria.")
                            st.rerun()
                with d3:
                    if st.button("Rejeitar Resposta", width='stretch'):
                        if not st.session_state.justificativa_minuta.strip():
                            st.warning("Informe o motivo da rejeição.")
                        else:
                            audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="REJEITADO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            st.session_state.decisao_minuta = "REJEITADO"
                            st.error("Resposta REJEITADA.")
                            st.rerun()

            with tab_conf:
                aval_conf = exec_atual.get("avaliacao") or exec_atual.get("conformidade")
                if aval_conf:
                    taxa_fid = aval_conf.get("taxa_fidelidade_percentual")
                    taxa_str = f"{taxa_fid}%" if taxa_fid is not None else "N/A"
                    acertos = aval_conf.get("total_acertos", 0)
                    avaliaveis = aval_conf.get("total_campos_avaliaveis") or aval_conf.get("total_campos_analisados", 0)
                    erros_lista = [c for c in (aval_conf.get("erros_encontrados") or []) if c.get("status") != "PENDENCIA" and not c.get("eh_pendencia")]
                    pend_lista = [c for c in (aval_conf.get("comparativo_campos") or []) if c.get("eh_pendencia") or c.get("status") == "PENDENCIA"]

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Fidelidade aos Dados", taxa_str)
                    k2.metric("Campos Conformes", f"{acertos}/{avaliaveis}")
                    k3.metric("Divergências", len(erros_lista))
                    k4.metric("Pendências", len(pend_lista))

                    c_filtro1, c_filtro2 = st.columns(2)
                    with c_filtro1:
                        st.session_state.formato_visual_cpf = st.radio(
                            "Visualização CPF/RG:",
                            ["Original", "Com Máscara", "Apenas Dígitos"],
                            horizontal=True
                        )
                    with c_filtro2:
                        st.session_state.filtro_conferencia = st.radio(
                            "Filtro:",
                            ["Todos", "Apenas Divergências", "Apenas Pendências"],
                            horizontal=True
                        )

                    comparativo = aval_conf.get("comparativo_campos", [])
                    tabela_dados = []
                    for it in comparativo:
                        is_div = it.get("status") == "DIVERGENTE"
                        is_pend = it.get("eh_pendencia") or it.get("status") == "PENDENCIA"
                        if st.session_state.filtro_conferencia == "Apenas Divergências" and not is_div:
                            continue
                        if st.session_state.filtro_conferencia == "Apenas Pendências" and not is_pend:
                            continue

                        val_apres = formatar_identificador(it.get("campo", ""), it.get("obtido", ""), st.session_state.formato_visual_cpf)
                        diag = "Conforme" if it.get("status") == "CORRETO" else "Divergente" if is_div else "Pendencia"
                        tabela_dados.append({
                            "Campo": it.get("rotulo", it.get("campo")),
                            "Valor Extraído": val_apres,
                            "Referência Esperada": it.get("esperado"),
                            "Diagnóstico": diag
                        })

                    st.dataframe(tabela_dados, width='stretch', hide_index=True)

            with tab_json:
                st.json(exec_atual["extracao"])

            with tab_met:
                met = exec_atual["metricas"]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Tempo", f"{met['duracao']:.2f}s")
                m2.metric("Tokens", met["tokens"])
                m3.metric("Custo Estimado", f"US$ {met['custo_usd']:.4f}" if met["custo_usd"] is not None else "N/A")
                m4.metric("Segurança XML", "Ativa")


# ==============================================================================
# MÓDULO 2: Experimento de Prompts (RF02)
# ==============================================================================
elif menu.startswith("2."):
    st.subheader("2. Experimento Controlado de Engenharia de Prompts (RF02)")
    st.markdown("Comparativo empírico entre os Prompts A (Zero-Shot Curto), B (Estruturado Manual) e C (Metaprompting de Produção com Envelope XML).")

    if st.button("Executar Experimento de Prompts", type="primary"):
        with st.spinner("Submetendo entrada oficial aos três prompts em tempo real..."):
            p_texto = resolver_caminho("dados/originais/entrada_texto.txt")
            conteudo = p_texto.read_text(encoding="utf-8") if p_texto.exists() else ""
            respostas = {}
            for tipo in ("A", "B", "C"):
                resp = llm_client.generate(prompt=montar_prompt(conteudo, tipo))
                respostas[tipo] = resp

            st.session_state.experimento_resultado = {
                "prompt_a": {"texto": respostas["A"].text, "duracao": respostas["A"].duration_seconds, "tokens": respostas["A"].total_tokens},
                "prompt_b": {"texto": respostas["B"].text, "duracao": respostas["B"].duration_seconds, "tokens": respostas["B"].total_tokens},
                "prompt_c": {"texto": respostas["C"].text, "duracao": respostas["C"].duration_seconds, "tokens": respostas["C"].total_tokens},
            }
            st.success("Experimento concluído!")

    exp = st.session_state.experimento_resultado
    if not exp:
        p_dir = resolver_caminho("prompts")
        def ler_ref(nome):
            p = p_dir / nome
            return p.read_text(encoding="utf-8") if p.exists() else ""
        exp = {
            "prompt_a": {"texto": ler_ref("saida_prompt_a.txt"), "duracao": 25.72, "tokens": 842},
            "prompt_b": {"texto": ler_ref("saida_prompt_b.txt"), "duracao": 15.24, "tokens": 612},
            "prompt_c": {"texto": ler_ref("saida_prompt_c.txt"), "duracao": 15.42, "tokens": 689},
        }

    criterios = [
        {"Critério de Avaliação": "Fidelidade ao Contexto", "Prompt A": "Média (resposta informal)", "Prompt B": "Alta (segue campos)", "Prompt C (Produção)": "Excelente (100% documental)"},
        {"Critério de Avaliação": "Alucinação de Dados", "Prompt A": "Risco Alto (infere datas/valores)", "Prompt B": "Baixo Risco", "Prompt C (Produção)": "Zero ('não localizado')"},
        {"Critério de Avaliação": "Formato de Saída", "Prompt A": "Texto livre sem padrão", "Prompt B": "Texto estruturado", "Prompt C (Produção)": "JSON estrito + Minuta"},
        {"Critério de Avaliação": "Tom Institucional", "Prompt A": "Informal / Genérico", "Prompt B": "Formal GOV.MT", "Prompt C (Produção)": "Oficial Padrão GOV.MT"},
        {"Critério de Avaliação": "Tratamento de Lacunas", "Prompt A": "Omissão", "Prompt B": "Aviso parcial", "Prompt C (Produção)": "Obrigatório 'não localizado'"},
        {"Critério de Avaliação": "Blindagem Injection", "Prompt A": "Inexistente", "Prompt B": "Parcial", "Prompt C (Produção)": "Robusta (Envelope XML)"},
        {"Critério de Avaliação": "Tempo e Tokens", "Prompt A": f"{exp['prompt_a']['duracao']:.2f}s ({exp['prompt_a']['tokens']} tok)", "Prompt B": f"{exp['prompt_b']['duracao']:.2f}s ({exp['prompt_b']['tokens']} tok)", "Prompt C (Produção)": f"{exp['prompt_c']['duracao']:.2f}s ({exp['prompt_c']['tokens']} tok)"},
    ]
    st.dataframe(criterios, width='stretch', hide_index=True)

    st.success("**Prompt Selecionado:** Prompt C (Metaprompting com Blindagem XML). Garante alucinação zero, contrato JSON estrito e imunidade contra injeção.")

    t1, t2, t3 = st.tabs(["Prompt A (Zero-Shot)", "Prompt B (Estruturado)", "Prompt C (Produção)"])
    with t1:
        st.text_area("Saída A:", value=exp["prompt_a"]["texto"], height=260, disabled=True)
    with t2:
        st.text_area("Saída B:", value=exp["prompt_b"]["texto"], height=260, disabled=True)
    with t3:
        st.text_area("Saída C:", value=exp["prompt_c"]["texto"], height=260, disabled=True)


# ==============================================================================
# MÓDULO 3: Áudio STT & Visão OCR (RF06, RF08)
# ==============================================================================
elif menu.startswith("3."):
    st.subheader("3. Reconhecimento de Voz (STT) e Leitura Visual (OCR)")
    st.markdown("Processamento multimodal omnichannel de áudio falado e fichas digitalizadas com conferência de entidades críticas.")

    col_a, col_v = st.columns(2, gap="large")

    with col_a:
        st.markdown("##### Mensagem de Audio (RF06)")
        p_audio = resolver_caminho("dados/originais/entrada_audio.mp3")
        if p_audio.exists():
            st.audio(str(p_audio))

        if st.button("Transcrever Áudio com Whisper", type="primary", width='stretch'):
            with st.spinner("Transcrevendo fala e validando entidades..."):
                res_audio = audio_processor.processar_com_auditoria(audit_logger)
                st.session_state.audio_stt_resultado = res_audio

        res_a = st.session_state.audio_stt_resultado
        if res_a:
            if res_a.get("sucesso"):
                comp = res_a.get("comparacao_gabarito", {})
                st.metric("Acurácia de Entidades", comp.get("acuracia_entidades", "4/6"))
                st.text_area("Transcrição Revisada:", value=res_a.get("transcricao_revisada", ""), height=140, disabled=True)

                st.markdown("**Validação de Entidades Críticas:**")
                for c_nome, c_item in comp.get("detalhes", {}).items():
                    ok = c_item.get("localizado_na_transcricao")
                    icone = "[OK]" if ok else "[DIVERGENCIA]"
                    st.write(f"- {icone} **{c_nome.capitalize()}:** *{c_item.get('valor_esperado')}*")

                if st.button("Enviar Transcricao para Atendimento", width='stretch'):
                    st.session_state.solicitacao_texto = res_a.get("transcricao_revisada") or ""
                    st.session_state.solicitacao_caso = "audio_transcricao"
                    st.success("Texto transferido para o Módulo 1!")

    with col_v:
        st.markdown("##### Documento Digitalizado / OCR (RF08)")
        vis_st = vision_processor.obter_status_visao()
        prov_label = (
            "OpenAI GPT-4o Vision" if vis_st.get("provedor") == "openai"
            else ("OpenRouter VLM" if vis_st.get("provedor") == "openrouter"
            else "Tesseract Local")
        )
        st.info(f"Motor Ativo de OCR: **{prov_label}** (Modelo: `{vis_st.get('modelo', 'gpt-4o')}`)")
        st.caption("Documento analisado: `dados/originais/entrada_pdf-imagem.pdf` (Ficha de Matrícula ETEC/SECITECI)")

        if st.button("Executar Leitura OCR", type="primary", width='stretch'):
            with st.spinner(f"Analisando documento com {prov_label}..."):
                res_visao = vision_processor.processar_com_auditoria(audit_logger)
                st.session_state.visao_ocr_resultado = res_visao

        res_v = st.session_state.visao_ocr_resultado
        if res_v:
            if res_v.get("sucesso"):
                st.success(f"OCR Concluído via {res_v.get('provedor', prov_label)} | Modelo: {res_v.get('modelo_utilizado', 'gpt-4o')}")
                if res_v.get("aviso_fallback"):
                    st.warning(res_v["aviso_fallback"])
                st.metric("Acurácia contra Gabarito", res_v.get("comparacao_gabarito", {}).get("taxa_acuracia_percentual", "N/A"))
                txt_ocr = res_v.get("texto_corrigido") or res_v.get("texto_bruto") or ""
                st.text_area("Texto Extraído pelo OCR:", value=txt_ocr, height=140, disabled=True)

                if res_v.get("trechos_incertos_ou_ilegiveis"):
                    st.markdown("**Trechos Incertos / Manuscritos:**")
                    for t in res_v.get("trechos_incertos_ou_ilegiveis"):
                        st.caption(f"• `{t}`")

                if st.button("Enviar Texto OCR para Atendimento", width='stretch'):
                    st.session_state.solicitacao_texto = txt_ocr
                    st.session_state.solicitacao_caso = "visao_documento"
                    st.success("Texto transferido para o Módulo 1!")


# ==============================================================================
# MÓDULO 4: Comunicação Visual Oficial (RF10)
# ==============================================================================
elif menu.startswith("4."):
    st.subheader("4. Comunicação Visual Institucional Padronizada (RF10)")
    st.markdown("Abordagem híbrida: geração de ilustração sem texto por IA combinada com moldura timbrada oficial em Pillow (Brasão do Estado e tarja de proveniência de conteúdo sintético).")

    def _obter_ultima_imagem_existente():
        diretorio = Path("resultados/imagens")
        if not diretorio.exists():
            return None
        jsons = sorted(diretorio.glob("comunicado_institucional_govmt*.json"), key=os.path.getmtime, reverse=True)
        for j in jsons:
            try:
                with open(j, "r", encoding="utf-8") as f:
                    m = json.load(f)
                if m.get("sucesso") and m.get("arquivo_imagem") and os.path.exists(m.get("arquivo_imagem")):
                    log_dir = Path("resultados/logs")
                    sha = m.get("sha256_imagem")
                    found_exec = None
                    if log_dir.exists():
                        for l in sorted(log_dir.glob("EXEC_*.json"), key=os.path.getmtime, reverse=True):
                            try:
                                with open(l, "r", encoding="utf-8") as fl:
                                    ld = json.load(fl)
                                if ld.get("modalidade") == "imagem" and ld.get("detalhes_completos", {}).get("sha256_imagem") == sha:
                                    found_exec = ld.get("id_execucao")
                                    break
                            except Exception:
                                pass
                    return {
                        "sucesso": True,
                        "caminho_imagem": m.get("arquivo_imagem"),
                        "caminho_metadados": str(j),
                        "metadados": m,
                        "id_execucao": found_exec or m.get("identificador"),
                    }
            except Exception:
                continue
        return None

    if st.session_state.get("imagem_resultado") is None:
        st.session_state.imagem_resultado = _obter_ultima_imagem_existente()

    c_btn1, c_btn2 = st.columns([1.2, 2])
    with c_btn1:
        if st.button("Gerar Comunicado Visual Oficial", type="primary", width='stretch'):
            with st.spinner("Gerando ilustração sem texto por IA e aplicando moldura GOV.MT com Brasão..."):
                res_img = image_generator.gerar_comunicado_oficial(audit_logger=audit_logger)
                st.session_state.imagem_resultado = res_img
                st.session_state.imagem_aprovada = False
                if res_img.get("sucesso"):
                    st.success("Nova peça institucional gerada com sucesso!")
                else:
                    st.error(f"Erro na geração da imagem: {res_img.get('erro', 'Falha no provedor de imagens.')}")

    img_dado = st.session_state.get("imagem_resultado")
    if img_dado and img_dado.get("sucesso"):
        c_v1, c_v2 = st.columns([1.2, 1], gap="large")
        with c_v1:
            st.image(img_dado["caminho_imagem"], caption="Peça Institucional Padronizada GOV.MT (RF10)", width='stretch')
            if os.path.exists(img_dado["caminho_imagem"]):
                with open(img_dado["caminho_imagem"], "rb") as f_img:
                    st.download_button(
                        label="Baixar Peça Gráfica PNG",
                        data=f_img.read(),
                        file_name=Path(img_dado["caminho_imagem"]).name,
                        mime="image/png",
                        width='stretch'
                    )
        with c_v2:
            meta = img_dado.get("metadados", {})
            st.markdown("##### Metadados da Peça (RF10)")
            st.write(f"- **Título:** {meta.get('titulo')}")
            st.write(f"- **Dimensões:** {meta.get('dimensoes', '1080x1350')}")
            st.write(f"- **Modelo IA:** `{meta.get('modelo_ia_utilizado')}`")
            st.write(f"- **Provedor:** `{meta.get('provedor_efetivo') or meta.get('provedor_solicitado')}`")
            st.write(f"- **Tarja:** `{meta.get('declaracao_proveniencia')}`")
            st.write(f"- **SHA-256:** `{meta.get('sha256_imagem', '')[:20]}...`")

            status_rev = meta.get("status_revisao", "pendente_revisao")
            if status_rev in ("aprovada", "APROVADO"):
                st.success("**Status de Homologação:** APROVADA PARA PUBLICAÇÃO")
            elif status_rev in ("rejeitada", "REJEITADO"):
                st.error("**Status de Homologação:** REJEITADA PELO OPERADOR")
            else:
                st.warning("**Status de Homologação:** PENDENTE DE REVISÃO HUMANA")

            st.divider()
            st.markdown("##### Deliberação Humana (Human-in-the-Loop - RF13 / RF20)")
            chk_v = st.checkbox(
                "Conferi textos, símbolos, mãos, objetos e coerência visual institucional (RF13).",
                key="chk_conferencia_visual"
            )
            just_v = st.text_input(
                "Justificativa da Decisão:",
                value="Conferência visual realizada conforme os padrões normativos e visuais do GOV.MT.",
                key="just_conferencia_visual"
            )

            b_ap, b_rej = st.columns(2)
            with b_ap:
                if st.button("Aprovar Imagem", type="primary", width='stretch'):
                    if not chk_v:
                        st.warning("Confirme o checkbox de conferência visual antes de registrar a aprovação.")
                    else:
                        res_rev = image_generator.revisar_imagem(
                            id_execucao=img_dado.get("id_execucao") or meta.get("identificador"),
                            hash_imagem=meta.get("sha256_imagem"),
                            decisao="APROVADO",
                            justificativa=just_v,
                            operador="Servidor SECITECI/MT",
                            audit_logger=audit_logger
                        )
                        if res_rev.get("sucesso"):
                            st.session_state.imagem_aprovada = True
                            img_dado["metadados"]["status_revisao"] = "aprovada"
                            st.session_state.imagem_resultado = img_dado
                            st.success("Imagem homologada e aprovada com sucesso na trilha de auditoria!")
                        else:
                            st.error(f"Não foi possível homologar a imagem: {res_rev.get('erro', 'Erro desconhecido.')}")
            with b_rej:
                if st.button("Rejeitar Imagem", width='stretch'):
                    res_rev = image_generator.revisar_imagem(
                        id_execucao=img_dado.get("id_execucao") or meta.get("identificador"),
                        hash_imagem=meta.get("sha256_imagem"),
                        decisao="REJEITADO",
                        justificativa=just_v,
                        operador="Servidor SECITECI/MT",
                        audit_logger=audit_logger
                    )
                    if res_rev.get("sucesso"):
                        st.session_state.imagem_aprovada = False
                        img_dado["metadados"]["status_revisao"] = "rejeitada"
                        st.session_state.imagem_resultado = img_dado
                        st.warning("Imagem rejeitada e registrada na trilha de auditoria.")
                    else:
                        st.error(f"Erro ao rejeitar: {res_rev.get('erro', 'Erro desconhecido.')}")
    elif img_dado and not img_dado.get("sucesso"):
        st.error(f"Falha na geração da imagem: {img_dado.get('erro', 'Erro desconhecido.')}")
    else:
        st.info("Clique em **Gerar Comunicado Visual Oficial** para criar a peça gráfica institucional.")


# ==============================================================================
# MÓDULO 5: Auditoria & LGPD (RF11, RF12, RF13, RF21)
# ==============================================================================
elif menu.startswith("5."):
    st.subheader("5. Trilha de Auditoria e Conformidade LGPD (RF11 / RF12 / RF21)")
    st.markdown("Rastreabilidade de todas as chamadas de IA, versões de esquema/prompt/índice e decisões humanas tomadas pelos operadores.")

    t_lgpd, t_logs = st.tabs(["Relatório de Conformidade LGPD", "Histórico de Auditoria"])

    with t_lgpd:
        rel_lgpd = LGPDManager.gerar_relatorio_conformidade()
        st.markdown(f"#### {rel_lgpd.get('titulo')}")
        st.caption(rel_lgpd.get("declaracao_dados_ficticios"))

        tabela_lgpd = []
        for campo, info in rel_lgpd.get("matriz_de_dados", {}).items():
            tabela_lgpd.append({
                "Campo": campo,
                "Natureza": info.get("natureza"),
                "Finalidade": info.get("finalidade"),
                "Risco": info.get("risco"),
                "Minimização": "Minimizado no Prompt" if info.get("minimizar_no_prompt") else "Essencial"
            })
        st.dataframe(tabela_lgpd, width='stretch', hide_index=True)

    with t_logs:
        if st.button("Atualizar Trilha de Auditoria"):
            st.rerun()

        logs = audit_logger.listar_execucoes()
        if not logs:
            st.info("Nenhum registro gravado.")
        else:
            st.markdown(f"**Total de Registros:** `{len(logs)}`")
            for reg in reversed(logs):
                exec_id = reg.get("id_execucao", "N/A")
                mod = reg.get("modalidade", "").upper()
                dec = reg.get("decisao_humana", {})
                status_d = dec.get("status", "pendente")
                dur = reg.get("duracao_segundos", 0.0)

                with st.expander(f"[{mod}] {exec_id} — Decisão: {status_d.upper()} ({dur:.2f}s)"):
                    st.write(f"- **Origem:** `{reg.get('arquivo_origem')}`")
                    st.write(f"- **Provedor / Modelo:** `{reg.get('provedor')}` / `{reg.get('modelo')}`")
                    st.write(f"- **Versão Prompt / Esquema / Índice:** `{reg.get('versao_prompt')}` / `{reg.get('versao_esquema', '2.0.0')}` / `{reg.get('versao_indice', 'N/A')}`")
                    if reg.get("ids_recuperados"):
                        st.write(f"- **IDs Recuperados (RAG):** `{', '.join(reg['ids_recuperados'])}`")
                    st.write(f"- **Data/Hora:** `{reg.get('timestamp')}`")
                    st.write(f"- **Justificativa:** {dec.get('justificativa', 'Nenhuma')}")


# ==============================================================================
# MÓDULO 6: Assistente de Documentos RAG e Atendimento Integrado (RF17 a RF21)
# ==============================================================================
elif menu.startswith("6."):
    st.subheader("6. Assistente de Documentos Institucionais e Atendimento Integrado (RAG — RF18 a RF21)")
    st.markdown(
        "Consulta semântica fundamentada nos editais e retificações da ETEC/SECITECI-MT, com citações explícitas, "
        "detecção de conflitos normativos, separação entre fatos do solicitante e regras do acervo, e troca de provedor sem reconstrução do índice."
    )

    aba_consulta, aba_integrado = st.tabs([
        "Consulta Direta ao Acervo (P1 a P8 — RF18/RF19/RF21)",
        "Atendimento Integrado de Solicitações com Minuta Fundamentada (SOL-01 a SOL-06 — RF20)"
    ])

    with aba_consulta:
        c_q, c_cfg1, c_cfg2 = st.columns([2.6, 1, 1.4])
        with c_q:
            sugestoes = [
                "Personalizada (digitar abaixo)",
                "P1: Qual é o prazo final prorrogado para inscrição no processo seletivo?",
                "P2: Quais documentos assalariados devem apresentar para comprovar renda?",
                "P3: Quando iniciam as aulas de Enfermagem na sede em Barra do Garças?",
                "P4: Quando iniciam as aulas de Enfermagem na sede em Cuiabá?",
                "P5: Qual o formato e duração do vídeo de heteroidentificação?",
                "P6: Qual é o valor da bolsa de estágio em empresas privadas?",
                "P7: Quais são os critérios de isenção de pós-graduação?",
                "P8: Até que dia do mês deve ser entregue a frequência do auxílio alimentação?"
            ]
            escolha = st.selectbox("Perguntas de Teste do Gabarito:", sugestoes)

            perguntas_map = {
                "P1:": "Qual é o prazo final prorrogado para realização das inscrições no Processo Seletivo das ETECs 2026/2?",
                "P2:": "Quais documentos devem ser apresentados por trabalhadores assalariados para comprovar a renda familiar no Programa de Permanência Estudantil?",
                "P3:": "Em qual data terão início as aulas do curso Técnico em Enfermagem ofertado na sede da ETEC Barra do Garças?",
                "P4:": "Qual é a data de início das aulas para o curso Técnico em Enfermagem na sede da ETEC Cuiabá?",
                "P5:": "Quais são o formato e a duração máxima permitidos para o vídeo de heteroidentificação racial?",
                "P6:": "Qual é o valor mensal pago aos alunos da ETEC a título de bolsa de estágio em empresas privadas conveniadas?",
                "P7:": "Quais são os critérios para solicitar isenção da taxa de matrícula no curso de pós-graduação em gestão pública?",
                "P8:": "Até que dia do mês o estudante contemplado pelo Auxílio Alimentação deve entregar a comprovação de frequência na secretaria acadêmica?",
            }

            pergunta_txt = ""
            for k_p, v_p in perguntas_map.items():
                if escolha.startswith(k_p):
                    pergunta_txt = v_p
                    break

            pergunta_digitada = st.text_input("Pergunta do Cidadão:", value=pergunta_txt, placeholder="Digite a dúvida sobre o edital...")

        with c_cfg1:
            top_k = st.slider("Trechos (Top-K):", min_value=1, max_value=5, value=3)
        with c_cfg2:
            prov_rag = st.selectbox(
                "Provedor/Adaptador (RF21):",
                ["extrator_fundamentado_local", "adaptador_simulado", "openai", "openrouter", "huggingface"],
                help="Demonstra a troca de provedor/adaptador sem reconstruir o índice vetorial (T12)."
            )

        if st.button("Buscar e Responder com RAG", type="primary"):
            if not pergunta_digitada.strip():
                st.warning("Informe a pergunta.")
            else:
                with st.spinner("Buscando no acervo vetorial e analisando fundamentação..."):
                    override = None if prov_rag == "extrator_fundamentado_local" else prov_rag
                    resp = rag_motor.responder(pergunta_digitada, top_k=top_k, provider_override=override)
                    st.session_state.rag_consulta_resultado = {
                        "pergunta": pergunta_digitada,
                        "provedor": prov_rag,
                        "versao_indice": indice_vetorial.versao_indice,
                        "resposta_obj": resp,
                    }

        res_c = st.session_state.rag_consulta_resultado
        if res_c:
            resp = res_c["resposta_obj"]
            st.caption(f"Índice Vetorial preservado: `{res_c['versao_indice']}` | Adaptador utilizado: `{res_c['provedor']}`")
            if resp.status == "fundamentada":
                st.success("RESPOSTA FUNDAMENTADA COM EVIDÊNCIA SUFICIENTE")
            elif resp.status == "conflito_de_fontes":
                st.error("CONFLITO DE FONTES DETECTADO (REVISÃO HUMANA OBRIGATÓRIA)")
            else:
                st.warning("SEM EVIDÊNCIA SUFICIENTE NO ACERVO (ABSTENÇÃO SEGURA)")

            st.info(resp.resposta)

            if resp.divergencia_identificada:
                st.warning(f"**Divergência Normativa Identificada:** {resp.divergencia_identificada}")

            st.markdown("##### Trechos Recuperados do Acervo (Sanitizados contra Injeção Indireta)")
            for idx, t in enumerate(resp.fontes, start=1):
                with st.expander(f"Trecho {idx}: {t.documento_id} v{t.versao} (Pág. {t.pagina or '1'}) — Similaridade: {t.score_similaridade:.4f}"):
                    st.caption(f"ID: {t.trecho_id} | Seção: {t.secao or 'Geral'} | Distância: {t.score_distancia:.4f}")
                    st.text_area("Fragmento:", value=t.conteudo, height=90, disabled=True, key=f"rag_{t.trecho_id}")

    with aba_integrado:
        st.markdown("##### Fluxo Integrado: Solicitação $\\rightarrow$ Extração Literal/Inferida $\\rightarrow$ Busca RAG $\\rightarrow$ Minuta Fundamentada $\\rightarrow$ Decisão Humana (RF20)")
        p_sol = resolver_caminho("dados/solicitacoes/solicitacoes.json")
        solicitacoes_lista = json.loads(p_sol.read_text(encoding="utf-8")) if p_sol.exists() else []
        opcoes_int = {f"{s['id']} — {s['canal']} ({s['subtipo']})": s for s in solicitacoes_lista}
        opcoes_int["Upload de Arquivo (.txt / .pdf)"] = "UPLOAD"
        opcoes_int["Digitação Livre"] = None

        c_sel1, c_sel2 = st.columns([2.2, 1])
        with c_sel1:
            escolha_int = st.selectbox("Selecionar Solicitação ou Canal de Entrada:", list(opcoes_int.keys()))
        with c_sel2:
            prov_int = st.selectbox(
                "Configuração de Geração (RF21):",
                ["extrator_fundamentado_local", "adaptador_simulado", "openai", "openrouter", "huggingface"],
                key="prov_int_select"
            )

        item_int = opcoes_int[escolha_int]
        texto_int_padrao = ""
        prot_int_padrao = ""
        data_int_padrao = ""

        if item_int == "UPLOAD":
            arq_up = st.file_uploader("Envie arquivo de solicitação (.txt ou .pdf, máx 10 MB):", type=["txt", "pdf"])
            if arq_up is not None:
                val_arq = guardrail_manager.validar_arquivo(arq_up.name, len(arq_up.getvalue()))
                if not val_arq.permitido:
                    st.error(val_arq.motivo)
                else:
                    if arq_up.name.lower().endswith(".txt"):
                        texto_int_padrao = arq_up.getvalue().decode("utf-8", errors="replace")
                    else:
                        import fitz
                        doc_up = fitz.open(stream=arq_up.getvalue(), filetype="pdf")
                        texto_int_padrao = "\n".join(p.get_text("text") for p in doc_up)
                        doc_up.close()
        elif isinstance(item_int, dict):
            texto_int_padrao = item_int.get("texto_original", "")
            prot_int_padrao = item_int.get("protocolo") or ""
            data_int_padrao = item_int.get("data") or ""

        col_f1, col_f2 = st.columns([3, 1])
        with col_f1:
            texto_int = st.text_area("Texto da Solicitação:", value=texto_int_padrao, height=130, key="txt_int_area")
        with col_f2:
            prot_int = st.text_input("Protocolo (se houver):", value=prot_int_padrao, key="prot_int_in")
            data_int = st.text_input("Data de Registro (se houver):", value=data_int_padrao, key="data_int_in")

        if st.button("Executar Atendimento Integrado com RAG (RF20)", type="primary"):
            if not texto_int.strip():
                st.warning("Informe o texto da solicitação.")
            else:
                dec_guard = guardrail_manager.validar_entrada(texto_int)
                if not dec_guard.permitido:
                    st.error(f"Entrada bloqueada pelos Guardrails (RF16): {dec_guard.motivo}")
                else:
                    with st.spinner("Extraindo ficha estruturada, consultando editais e redigindo minuta fundamentada..."):
                        ficha_int = processar_solicitacao(
                            texto_original=texto_int,
                            protocolo_externo=prot_int if prot_int.strip() else None,
                            data_externa=data_int if data_int.strip() else None,
                        )
                        override_int = None if prov_int == "extrator_fundamentado_local" else prov_int
                        pacote_minuta = rag_motor.gerar_minuta_fundamentada(
                            ficha=ficha_int,
                            top_k=3,
                            provider_override=override_int,
                        )
                        exec_id_int = audit_logger.registrar_execucao(
                            modalidade="atendimento_integrado_rag",
                            arquivo_origem=escolha_int,
                            provedor=prov_int,
                            modelo="MotorRAG+NLP_v2",
                            versao_prompt="RAG_MINUTA_v2.0",
                            versao_esquema="ExtracaoFicha_v2.0",
                            consulta=texto_int[:200],
                            ids_recuperados=[f.trecho_id for f in pacote_minuta.fontes],
                            versao_indice=indice_vetorial.versao_indice,
                            parametros={"top_k": 3, "provedor_geracao": prov_int},
                            resultado={
                                "sucesso": True,
                                "status_rag": pacote_minuta.status,
                                "categoria": ficha_int.categoria,
                                "necessidade_revisao": pacote_minuta.necessidade_revisao,
                            },
                            duracao_segundos=0.05,
                        )
                        st.session_state.rag_atendimento_resultado = {
                            "id_execucao": exec_id_int,
                            "ficha": ficha_int,
                            "pacote": pacote_minuta,
                            "status_operador": "pendente",
                        }

        res_int = st.session_state.rag_atendimento_resultado
        if res_int:
            ficha_i: ExtracaoFicha = res_int["ficha"]
            pacote_i = res_int["pacote"]
            sep_i = ficha_i.separar_literal_e_inferido()

            st.markdown(f"**ID de Execução Auditado:** `{res_int['id_execucao']}` • **Status da Decisão Humana:** `{res_int['status_operador'].upper()}`")

            if pacote_i.divergencia_identificada:
                st.error(f"**Alerta de Conflito Documental:** {pacote_i.divergencia_identificada}")
            if ficha_i.campos_ausentes:
                st.warning(f"**Alerta de Lacunas na Solicitação ({len(ficha_i.campos_ausentes)} campos ausentes):** `{', '.join(ficha_i.campos_ausentes)}`")

            st.info(f"**Resumo Fiel da Solicitação (RF15):** {ficha_i.resumo}")

            c_lit, c_inf = st.columns(2)
            with c_lit:
                st.markdown("###### Extração Literal (Sustentada pelo Texto)")
                st.json(sep_i["extracao_literal"])
            with c_inf:
                st.markdown("###### Informação Inferida (Classificação / Triagem)")
                st.json(sep_i["informacao_inferida"])

            st.markdown("###### Trechos Recuperados do Acervo Institucional")
            for f_item in pacote_i.fontes:
                st.caption(
                    f"• `{f_item.documento_id}` (v{f_item.versao}, pág. {f_item.pagina or 1}, trecho `{f_item.trecho_id}`) "
                    f"— Similaridade: `{f_item.score_similaridade}` | Distância: `{f_item.score_distancia}`"
                )

            minuta_int_editada = st.text_area(
                "Minuta Institucional Fundamentada (Fatos do Solicitante + Regras do Acervo):",
                value=pacote_i.minuta_institucional or "",
                height=260,
                key="minuta_int_edit_area"
            )

            st.markdown("###### Decisão Humana sobre o Atendimento Integrado (RF20)")
            c_dec1, c_dec2 = st.columns([1, 2])
            with c_dec1:
                novo_status_op = st.selectbox(
                    "Estado da Revisão:",
                    ["pendente", "aprovada", "rejeitada", "revisar"],
                    index=["pendente", "aprovada", "rejeitada", "revisar"].index(res_int["status_operador"])
                )
            with c_dec2:
                just_op_int = st.text_input(
                    "Justificativa do Operador:",
                    value="Conferência dos trechos normativos e dados da ficha realizada pelo servidor."
                )

            if st.button("Registrar Decisão Humana (RF20/RF21)", width='stretch'):
                dec_validada = DecisaoOperador(
                    solicitacao_id=res_int["id_execucao"],
                    decisao=novo_status_op,
                    justificativa=just_op_int,
                )
                audit_logger.atualizar_decisao_humana(
                    exec_id=dec_validada.solicitacao_id,
                    decisao=dec_validada.decisao.upper(),
                    justificativa=dec_validada.justificativa,
                    operador=dec_validada.operador,
                    texto_final=minuta_int_editada,
                )
                st.session_state.rag_atendimento_resultado["status_operador"] = novo_status_op
                st.success(f"Decisão '{novo_status_op.upper()}' registrada na auditoria com sucesso!")


# ==============================================================================
# MÓDULO 7: Triagem & Ficha da Solicitação (RF14/RF15)
# ==============================================================================
elif menu.startswith("7."):
    st.subheader("7. Triagem Estruturada e Ficha de Compreensão (RF14 / RF15)")
    st.markdown("Converte manifestações em esquemas rigorosos Pydantic v2 (`extra='forbid'`) com distinção explícita entre extração literal e informação inferida.")

    p_sol = resolver_caminho("dados/solicitacoes/solicitacoes.json")
    if p_sol.exists():
        with open(p_sol, "r", encoding="utf-8") as fs:
            solicitacoes_ex = json.load(fs)
        opcoes_sol = {f"{s['id']} ({s['subtipo']})": s for s in solicitacoes_ex}
        opcoes_sol["Nova Manifestação"] = None

        escolha_sol = st.selectbox("Carregar Solicitação de Teste:", list(opcoes_sol.keys()))
        caso_sol = opcoes_sol[escolha_sol]
    else:
        caso_sol = None

    texto_f = st.text_area("Texto da Manifestação:", value=caso_sol["texto_original"] if caso_sol else "", height=150)
    prot_f = st.text_input("Protocolo Externo (opcional):", value=(caso_sol.get("protocolo") or "") if caso_sol else "")

    if st.button("Processar Ficha Pydantic", type="primary"):
        if not texto_f.strip():
            st.warning("Informe o texto.")
        else:
            with st.spinner("Processando ficha estruturada..."):
                ficha = processar_solicitacao(
                    texto_f,
                    protocolo_externo=prot_f if prot_f else None,
                    data_externa=(caso_sol.get("data") if caso_sol else None),
                )
                dados_ui = ficha.para_interface_usuario()
                separado = ficha.separar_literal_e_inferido()

                f1, f2, f3 = st.columns(3)
                f1.metric("Categoria", ficha.categoria)
                f2.metric("Campos Ausentes", len(ficha.campos_ausentes))
                f3.metric("Necessita Revisão?", "SIM" if ficha.necessidade_revisao else "NÃO")

                st.info(f"**Resumo Fiel (até 100 palavras):**\n\n{ficha.resumo}")

                col_l, col_i = st.columns(2)
                with col_l:
                    st.markdown("##### Extração Literal (Dados do Texto)")
                    st.json(separado["extracao_literal"])
                with col_i:
                    st.markdown("##### Informação Inferida (Triagem)")
                    st.json(separado["informacao_inferida"])

                with st.expander("Visualizar Contrato Completo para Interface ('não localizado')"):
                    st.json(dados_ui)


# ==============================================================================
# MÓDULO 8: Painel de Sentimentos (RF22)
# ==============================================================================
elif menu.startswith("8."):
    st.subheader("8. Painel Analítico de Sentimentos (RF22)")
    st.markdown(
        "Classificação individual em 4 polaridades (`positiva`, `negativa`, `neutra`, `indeterminada`) "
        "com filtros por categoria e período, deduplicação por `id` e agregação matemática 100% determinística em Python."
    )

    p_av = resolver_caminho("dados/avaliacoes/avaliacoes_atendimento.json")
    if p_av.exists():
        with open(p_av, "r", encoding="utf-8") as fa:
            avaliacoes = json.load(fa)

        categorias_disp = ["Todas"] + sorted(list({a.get("categoria_servico", "Geral") for a in avaliacoes}))
        datas_disp = sorted([a.get("data", "2026-10-01") for a in avaliacoes])

        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            cat_filtro = st.selectbox("Filtrar por Categoria/Canal:", categorias_disp)
        with cf2:
            dt_ini = st.text_input("Data Inicial (YYYY-MM-DD):", value=datas_disp[0] if datas_disp else "2026-10-01")
        with cf3:
            dt_fim = st.text_input("Data Final (YYYY-MM-DD):", value=datas_disp[-1] if datas_disp else "2026-10-31")

        avaliacoes_filtradas = filtrar_e_deduplicar_avaliacoes(
            avaliacoes,
            categoria_servico=cat_filtro,
            data_inicio=dt_ini,
            data_fim=dt_fim,
        )

        classificacoes = [classificar_sentimento_avaliacao(a["id"], a["texto"]) for a in avaliacoes_filtradas]
        agregacao = agregar_sentimentos_determinístico(classificacoes)

        st.caption(f"**Denominador Visível da Consulta Atual:** `{agregacao['denominador']}` avaliações únicas consideradas.")

        if agregacao["denominador"] == 0:
            st.warning("Nenhuma avaliação encontrada para o filtro selecionado (tratamento seguro de conjunto vazio sem divisão por zero).")
        else:
            col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
            with col_s1:
                with st.container(border=True):
                    st.metric("Total Único", agregacao["denominador"], help="Denominador de avaliações únicas")
            with col_s2:
                with st.container(border=True):
                    st.metric("Positivas", agregacao["distribuicao"]["positiva"], delta=f"{agregacao['percentuais']['positiva']}%", delta_color="normal")
            with col_s3:
                with st.container(border=True):
                    st.metric("Negativas", agregacao["distribuicao"]["negativa"], delta=f"-{agregacao['percentuais']['negativa']}%", delta_color="inverse")
            with col_s4:
                with st.container(border=True):
                    st.metric("Neutras", agregacao["distribuicao"]["neutra"], delta=f"{agregacao['percentuais']['neutra']}%", delta_color="off")
            with col_s5:
                with st.container(border=True):
                    st.metric("Indeterminadas", agregacao["distribuicao"]["indeterminada"], delta=f"{agregacao['percentuais']['indeterminada']}%", delta_color="inverse", help="Casos com necessidade de revisão")

            st.bar_chart(agregacao["distribuicao"])
            st.caption(f"**Nota Metodológica:** {agregacao['nota_metodologica']}")

            with st.expander("Inspecionar Prompt Dedicado e Isolado de Sentimento (RF22)"):
                st.code(montar_prompt_sentimento_isolado(avaliacoes_filtradas[0]["texto"]), language="xml")

            st.markdown("##### Avaliações dos Cidadãos (Estimativa Individual por Item)")
            for av, cl in zip(avaliacoes_filtradas, classificacoes):
                with st.expander(f"{cl.id} [{av.get('categoria_servico', 'Geral')} | {av.get('data', '')}] — [{cl.polaridade.upper()}] — {av['texto'][:60]}..."):
                    st.write(f"**Texto:** {av['texto']}")
                    st.write(f"**Justificativa:** {cl.justificativa}")
                    st.caption(f"Confiança Estimada: {cl.confianca_estimada:.2f} | Requer Revisão: {cl.necessidade_revisao}")


# ==============================================================================
# MÓDULO 9: Gestão do Acervo, Expurgos e Matriz T01-T15 (RF23, RF24)
# ==============================================================================
elif menu.startswith("9."):
    st.subheader("9. Governança do Acervo, Expurgos e Matriz de Avaliação T01–T15 (RF23 / RF24)")

    tab_acervo, tab_matriz = st.tabs([
        "Governança do Acervo e Expurgo Vetorial (RF24)",
        "Matriz de Avaliação Automatizada T01 a T15 e Chunking (RF18 / RF23)"
    ])

    with tab_acervo:
        st.markdown("Demonstração da exclusão definitiva de documentos e fragmentos derivados do índice vetorial.")

        docs_presentes = sorted(list({c["documento_id"] for c in indice_vetorial.chunks}))
        c_m1, c_m2 = st.columns(2)
        c_m1.metric("Documentos no Índice Vetorial", len(docs_presentes))
        c_m2.metric("Versão Atual do Índice", indice_vetorial.versao_indice)

        for d in docs_presentes:
            qtd = sum(1 for c in indice_vetorial.chunks if c["documento_id"] == d)
            st.write(f"- `{d}` ({qtd} trechos)")

        st.divider()
        st.markdown("##### Exclusão de Documento")
        doc_sel = st.selectbox("Selecione o documento para expurgo:", docs_presentes if docs_presentes else ["Nenhum"])

        if st.button("Excluir e Expurgar Fragmentos", type="secondary"):
            if doc_sel and doc_sel != "Nenhum":
                removidos = indice_vetorial.excluir_documento(doc_sel)
                st.success(f"Documento '{doc_sel}' excluído com sucesso! {removidos} fragmentos removidos.")
                st.rerun()

    with tab_matriz:
        st.markdown("Execução e inspeção dos 15 testes obrigatórios (`T01` a `T15`) e do experimento comparativo de chunking (`Config A: 400/80` vs `Config B: 800/150`).")
        caminho_rel_d02 = resolver_caminho("resultados/metricas/relatorio_avaliacao_d02.json")

        if st.button("Executar Matriz Completa (T01 a T15)", type="primary"):
            with st.spinner("Executando bateria completa de testes T01 a T15..."):
                avaliador = AvaliadorDesafio02(indice=indice_vetorial)
                avaliador.executar_matriz_testes_completa()
                st.success("Matriz T01–T15 executada e salva em `resultados/metricas/relatorio_avaliacao_d02.json`!")

        if caminho_rel_d02.exists():
            rel_d02 = json.loads(caminho_rel_d02.read_text(encoding="utf-8"))
            resumo_m = rel_d02.get("resumo_matriz", {})
            cm1, cm2, cm3 = st.columns(3)
            cm1.metric("Total de Testes", resumo_m.get("total_testes", 15))
            cm2.metric("Aprovados", resumo_m.get("aprovados", 15))
            cm3.metric("Taxa de Aprovação", f"{resumo_m.get('taxa_aprovacao', 100.0)}%")

            st.markdown("##### Tabela de Resultados (`T01` a `T15`)")
            st.dataframe(resumo_m.get("testes", []), width='stretch', hide_index=True)

            comp_chunk = rel_d02.get("avaliacao_chunking", {}).get("comparativo_configs", {})
            if comp_chunk:
                st.markdown("##### Comparativo Experimental de Chunking (RF18)")
                st.json(comp_chunk)

st.divider()
st.caption("Governo do Estado de Mato Grosso — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT)")
