"""
app.py - Interface Unificada Oficial Streamlit da Central Inteligente de Atendimento - GOV.MT
Interface oficial consolidada para os Desafios Práticos 01 (RF01 a RF13) e 02 (RF14 a RF24).
"""

import os
import sys
import subprocess
import time
from dotenv import load_dotenv

load_dotenv()
import json
import uuid
import re
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional
import streamlit as st
import pandas as pd
import altair as alt

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

# A tradução automática pode substituir nós de texto controlados pelo React,
# corrompendo rótulos e causando removeChild durante a navegação. A interface
# já está em português; alteramos apenas atributos, nunca os filhos do DOM.
from streamlit.components.v1 import html as componente_html
getattr(st, "iframe", componente_html)("""<script>
const raiz = window.parent.document.documentElement;
raiz.setAttribute('lang', 'pt-BR');
raiz.setAttribute('translate', 'no');
raiz.classList.add('notranslate');
</script>""", height=1)

# Estilos globais: força 100% de opacidade e máxima legibilidade em campos não editáveis
st.markdown("""
<style>
textarea:disabled,
input:disabled,
[disabled],
[aria-disabled="true"],
.stTextArea textarea:disabled,
.stTextInput input:disabled,
[data-baseweb="input"] input:disabled,
[data-baseweb="textarea"] textarea:disabled,
[data-testid="stTextArea"] textarea:disabled,
[data-testid="stTextInput"] input:disabled {
    opacity: 1.0 !important;
    -webkit-text-fill-color: #0f172a !important;
    color: #0f172a !important;
    background-color: #ffffff !important;
    border: 1px solid #94a3b8 !important;
    cursor: default !important;
}

[data-baseweb="base-input"],
[data-baseweb="textarea"],
.stTextArea div[data-baseweb="textarea"],
.stTextInput div[data-baseweb="base-input"] {
    opacity: 1.0 !important;
    background-color: #ffffff !important;
}

blockquote {
    opacity: 1.0 !important;
    color: #0f172a !important;
    font-style: normal !important;
    border-left: 4px solid #2563eb !important;
    background-color: #ffffff !important;
}

.stCaption, [data-testid="stCaptionContainer"] {
    opacity: 1.0 !important;
    color: #1e293b !important;
}
</style>
""", unsafe_allow_html=True)

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

def obter_provedores_disponiveis_rag():
    """Retorna apenas provedores configurados e prontos para uso (RF21)."""
    opcoes = ["extrator_fundamentado_local"]
    tem_oa = bool(os.getenv("OPENAI_API_KEY", "").strip())
    tem_or = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    tem_hf = bool(os.getenv("HF_TOKEN", "").strip())

    if tem_oa:
        opcoes.append("openai")
    if tem_or:
        opcoes.append("openrouter")
    if tem_hf:
        opcoes.append("huggingface")
    
    opcoes.append("adaptador_simulado")
    return opcoes


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
if "testes_ao_vivo" not in st.session_state:
    st.session_state.testes_ao_vivo = None
if "teste_individual_resultado" not in st.session_state:
    st.session_state.teste_individual_resultado = None
if "pytest_resultado" not in st.session_state:
    st.session_state.pytest_resultado = None

# ==============================================================================
# Ajuste Dinâmico de Altura e CSS para Exibição Integral
# ==============================================================================
st.markdown(
    """
    <style>
    /* Força o Streamlit a libertar a altura fixa injetada por JavaScript */
    div[data-baseweb="textarea"] > div {
        height: auto !important;
        min-height: fit-content !important;
    }
    textarea {
        field-sizing: content !important;
        height: auto !important;
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        line-height: 1.45 !important;
        resize: none !important; /* Desativa a pega de redimensionamento manual */
    }

    /* Campos de visualização (disabled) 100% opacos, com contraste nítido e fundo sólido */
    textarea:disabled,
    textarea[disabled] {
        opacity: 1 !important;
        -webkit-text-fill-color: #1e293b !important;
        color: #1e293b !important;
        background-color: #f1f5f9 !important;
        cursor: default !important;
    }
    div[data-baseweb="textarea"]:has(textarea:disabled) {
        opacity: 1 !important;
        background-color: #f1f5f9 !important;
        border-color: #cbd5e1 !important;
    }

    /* Reduz o espaco vazio no topo da tela principal sem cortar a borda superior */
    .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 3.2rem !important;
        padding-bottom: 2rem !important;
    }

    /* Reduz espacamento e bordas no brasao e cabecalho da barra lateral */
    [data-testid="stSidebar"] [data-testid="stImage"] {
        margin-top: -12px !important;
        margin-bottom: 2px !important;
        padding: 0 !important;
    }
    [data-testid="stSidebar"] hr {
        margin-top: 0.45rem !important;
        margin-bottom: 0.45rem !important;
    }
    [data-testid="stAppViewContainer"] { background-color: #f8fafc; }
    [data-testid="stSidebar"] { background-color: #eef4fa; }
    h1, h2, h3 { color: #004a8f; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px; }
    [data-testid="stMetricValue"] {
        white-space: normal;
        overflow-wrap: anywhere;
        font-size: clamp(1.2rem, 2.2vw, 2rem);
    }
    [data-testid="stMetricLabel"] p { white-space: normal; }
    div[data-baseweb="select"] [role="combobox"] {
        min-height: 2.5rem;
        line-height: 1.5;
    }
    /* Acabamento institucional com componentes nativos e sem alterar o DOM. */
    [data-testid="stMainBlockContainer"] { max-width: 1480px; }
    h2 { font-size: 1.7rem; line-height: 1.25; }
    h3 { font-size: 1.35rem; margin-top: 0.5rem; }
    h4, h5, h6 { color: #263f58; }
    [data-testid="stHeadingWithActionElements"] { padding-bottom: 0.35rem; }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        border-color: #dbe4ee;
        background-color: #ffffff;
    }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dbe4ee;
        border-top: 3px solid #004a8f;
        border-radius: 8px;
        padding: 0.85rem 1rem;
        height: 100%;
    }
    [data-testid="stMetricLabel"] { color: #475569; }
    [data-testid="stBaseButton-primary"] {
        background-color: #004a8f;
        border-color: #004a8f;
        color: #ffffff;
    }
    [data-testid="stBaseButton-primary"]:hover { background-color: #003c73; }
    [data-testid="stBaseButton-secondary"], [data-testid="stDownloadButton"] button {
        border-color: #c5d3e1;
        color: #004a8f;
    }
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
        border-radius: 8px;
        min-height: 2.6rem;
        font-weight: 600;
    }
    [data-testid="stButton"] button:disabled { opacity: 0.55; }
    div[data-baseweb="input"], div[data-baseweb="select"] > div,
    div[data-baseweb="textarea"] { border-radius: 8px; }
    [data-testid="stAlert"] { border-radius: 8px; line-height: 1.5; }
    [data-testid="stExpander"] { border-color: #dbe4ee; border-radius: 8px; }
    [data-baseweb="tab-list"] { gap: 0.5rem; border-bottom: 1px solid #dbe4ee; }
    [data-baseweb="tab"] { padding: 0.65rem 0.8rem; height: auto; }
    [data-baseweb="tab"][aria-selected="true"] {
        color: #004a8f; background: #e8f0f9; border-radius: 6px 6px 0 0;
    }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: 0.35rem; align-items: stretch; }
    [data-testid="stSidebar"] [role="radiogroup"] > div { width: 100%; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        align-items: center;
        padding: 0.5rem 0.55rem;
        margin: 0;
        border: 1px solid transparent;
        border-left: 3px solid transparent;
        border-radius: 7px;
        width: 100%;
        box-sizing: border-box;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #e2ebf5; }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: #ffffff; border-color: #cbdbea; border-left-color: #004a8f;
    }
    [data-testid="stSidebar"] [role="radiogroup"] p {
        font-size: 0.88rem; line-height: 1.3; margin-bottom: 0;
    }
    [data-testid="stSidebar"] [role="radiogroup"] [data-testid="stCaptionContainer"] p {
        font-size: 0.72rem; color: #52677c; margin-top: 0.18rem;
    }
    [data-testid="stSidebar"] [role="radiogroup"] small { color: #52677c; opacity: 1; }
    [data-testid="stSidebar"] [data-testid="stExpander"] { background: #ffffff; }
    [data-testid="stSidebar"] hr { border-color: #cfdae6; margin: 1rem 0 !important; }
    </style>
    """,
    unsafe_allow_html=True
)


def calcular_altura_dinamica(
    texto: Any,
    min_height: int = 80,
    max_height: int = 1800,
    chars_per_line: int = 85,  # Ponto de quebra conservador para evitar cortes
    line_height: int = 24      # Espaçamento vertical real da fonte
) -> int:
    """Calcula dinamicamente a altura ideal em píxeis com precisão,
    evitando cortes na base e margens vazias exageradas."""
    if not texto:
        return min_height
    texto_str = str(texto).strip()
    if not texto_str:
        return min_height
        
    linhas = texto_str.splitlines()
    total_linhas = 0
    for linha in linhas:
        if not linha:
            total_linhas += 1
        else:
            # Calcula quebras visuais assumindo um ecrã mais apertado
            quebras = max(1, (len(linha) + chars_per_line - 1) // chars_per_line)
            total_linhas += quebras
            
    # 30px exatos para cobrir o padding superior (12px) e inferior (12px) + bordas
    altura = (total_linhas * line_height) + 30
    return max(min_height, min(altura, max_height))


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
    st.sidebar.image(str(p_brasao), width=75)

st.sidebar.markdown(
    """
    <div style='margin-top: -6px; margin-bottom: 2px;'>
        <div style='font-size: 1.15rem; font-weight: 700; color: #0f172a; line-height: 1.2;'>Central GOV.MT</div>
        <div style='font-size: 0.82rem; color: #475569; margin-top: 2px;'><strong>SECITECI/MT</strong> • ETEC Cuiabá</div>
    </div>
    """,
    unsafe_allow_html=True
)
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
        "9. Gestao do Acervo e Expurgo (RF24)",
        "10. Matriz de Testes Automatizados T01-T15",
    ],
    index=0,
    format_func=lambda valor: {
        "1": "1. Atendimento ao cidadão",
        "2": "2. Experimento de prompts",
        "3": "3. Áudio e leitura visual",
        "4": "4. Comunicação visual",
        "5": "5. Auditoria e LGPD",
        "6": "6. Assistente documental",
        "7": "7. Triagem e ficha",
        "8": "8. Painel de sentimentos",
        "9": "9. Gestão do acervo",
        "10": "10. Matriz de testes",
    }[valor.split(".")[0]],
    captions=[
        "RF01–RF13 · Revisão humana", "RF02 · Comparação A/B/C",
        "RF06 / RF08 · STT e OCR", "RF10 · Peças institucionais",
        "RF11–RF13 / RF21 · Rastreabilidade", "RF18–RF21 · RAG",
        "RF14 / RF15 · Compreensão", "RF22 · Avaliações",
        "RF24 · Expurgo", "RF23 / RF24 · T01–T15",
    ],
)

st.sidebar.divider()
st.sidebar.markdown("##### Motores de IA")
st.sidebar.caption("Status real · Abra uma seção para conferir o provedor e o modelo.")

status_motores = obter_status_todos_motores()

with st.sidebar.expander("Texto / LLM", expanded=False):
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
st.sidebar.caption("Governança · Revisão humana obrigatória")

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
    st.subheader("1. Atendimento ao Cidadão e Redação de Minuta Oficial (RF01 a RF05, RF09)")
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
            height=calcular_altura_dinamica(st.session_state.solicitacao_texto, min_height=100),
            placeholder="Digite ou cole aqui a solicitação do cidadão..."
        )
        st.session_state.solicitacao_texto = texto_digitado

        c_btn1, c_btn2 = st.columns([1.5, 1])
        with c_btn1:
            btn_processar = st.button("Processar Solicitação", type="primary", width='stretch')
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
            with st.spinner("Processando a solicitação com validação e isolamento de segurança XML..."):
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
                "Painel de Conferência (RF13)",
                "JSON Estruturado (RF05)",
                "Métricas e qualidade"
            ])

            with tab_minuta:
                aval = exec_atual.get("avaliacao") or exec_atual.get("conformidade")
                if aval:
                    erros = [c for c in (aval.get("erros_encontrados") or []) if c.get("status") != "PENDENCIA" and not c.get("eh_pendencia")]
                    pends = [c for c in (aval.get("comparativo_campos") or []) if c.get("eh_pendencia") or c.get("status") == "PENDENCIA"]
                    if erros:
                        st.error(f"Atenção, operador: Foram detectadas {len(erros)} divergência(s) em relação aos padrões oficiais.")
                    elif pends:
                        st.warning(f"Dados pendentes na fonte: {len(pends)} campo(s) assinalados estritamente como *'não localizado'*.")
                    else:
                        st.success("Todos os campos extraídos estão conformes com os critérios oficiais.")

                texto_editado = st.text_area(
                    "Minuta de Despacho (Editável pelo Operador):",
                    value=st.session_state.minuta_editavel,
                    height=calcular_altura_dinamica(st.session_state.minuta_editavel, min_height=140),
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
                    if st.button("Sintetizar Voz Acessível (RF07)", width='stretch'):
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
                st.markdown("###### Deliberação do Servidor Responsável (RF13)")
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
                            salvo = audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="APROVADO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            if not salvo:
                                st.error("Não foi possível persistir a decisão. Tente novamente; a minuta continua pendente.")
                                st.stop()
                            st.session_state.decisao_minuta = "APROVADO"
                            st.success("Resposta APROVADA e homologada no log de auditoria!")
                            st.rerun()
                with d2:
                    if st.button("Salvar Correção", width='stretch'):
                        if not st.session_state.justificativa_minuta.strip():
                            st.warning("Preencha a justificativa da correção.")
                        else:
                            salvo = audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="CORRIGIDO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            if not salvo:
                                st.error("Não foi possível persistir a correção.")
                                st.stop()
                            st.session_state.decisao_minuta = "CORRIGIDO"
                            st.warning("Correção salva no log de auditoria.")
                            st.rerun()
                with d3:
                    if st.button("Rejeitar Resposta", width='stretch'):
                        if not st.session_state.justificativa_minuta.strip():
                            st.warning("Informe o motivo da rejeição.")
                        else:
                            salvo = audit_logger.atualizar_decisao_humana(
                                exec_id=exec_atual["id_execucao"],
                                decisao="REJEITADO",
                                justificativa=st.session_state.justificativa_minuta,
                                texto_final=st.session_state.minuta_editavel
                            )
                            if not salvo:
                                st.error("Não foi possível persistir a rejeição.")
                                st.stop()
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
    st.subheader("2. Experimento Comparativo de Prompts (Prompts A, B e C — RF02)")
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
        st.info("Nenhum experimento executado nesta sessão. Clique no botão 'Executar Experimento de Prompts' acima para submeter a entrada oficial aos Prompts A, B e C e visualizar os resultados em tempo real.")
    else:
        criterios = [
            {"Critério de Avaliação": "Fidelidade ao Contexto", "Prompt A": "Média (resposta informal)", "Prompt B": "Alta (segue campos)", "Prompt C (Produção)": "Exige conferência documental"},
            {"Critério de Avaliação": "Alucinação de Dados", "Prompt A": "Risco Alto (infere datas/valores)", "Prompt B": "Baixo Risco", "Prompt C (Produção)": "Zero ('não localizado')"},
            {"Critério de Avaliação": "Formato de Saída", "Prompt A": "Texto livre sem padrão", "Prompt B": "Texto estruturado", "Prompt C (Produção)": "JSON estrito + Minuta"},
            {"Critério de Avaliação": "Tom Institucional", "Prompt A": "Informal / Genérico", "Prompt B": "Formal GOV.MT", "Prompt C (Produção)": "Oficial Padrão GOV.MT"},
            {"Critério de Avaliação": "Tratamento de Lacunas", "Prompt A": "Omissão", "Prompt B": "Aviso parcial", "Prompt C (Produção)": "Obrigatório 'não localizado'"},
            {"Critério de Avaliação": "Blindagem Injection", "Prompt A": "Inexistente", "Prompt B": "Parcial", "Prompt C (Produção)": "Robusta (Envelope XML)"},
            {"Critério de Avaliação": "Tempo e Tokens", "Prompt A": f"{exp['prompt_a']['duracao']:.2f}s ({exp['prompt_a']['tokens']} tok)", "Prompt B": f"{exp['prompt_b']['duracao']:.2f}s ({exp['prompt_b']['tokens']} tok)", "Prompt C (Produção)": f"{exp['prompt_c']['duracao']:.2f}s ({exp['prompt_c']['tokens']} tok)"},
        ]
        st.dataframe(criterios, width='stretch', hide_index=True)

        st.success("**Prompt selecionado:** Prompt C, com estrutura JSON e isolamento XML. A fidelidade dos dados e a resposta exigem conferência humana.")

        t1, t2, t3 = st.tabs(["Prompt A (Zero-Shot)", "Prompt B (Estruturado)", "Prompt C (Produção)"])
        with t1:
            st.text_area("Saída A:", value=exp["prompt_a"]["texto"], height=calcular_altura_dinamica(exp["prompt_a"]["texto"], min_height=100), disabled=True)
        with t2:
            st.text_area("Saída B:", value=exp["prompt_b"]["texto"], height=calcular_altura_dinamica(exp["prompt_b"]["texto"], min_height=100), disabled=True)
        with t3:
            st.text_area("Saída C:", value=exp["prompt_c"]["texto"], height=calcular_altura_dinamica(exp["prompt_c"]["texto"], min_height=100), disabled=True)


# ==============================================================================
# MÓDULO 3: Áudio STT & Visão OCR (RF06, RF08)
# ==============================================================================
elif menu.startswith("3."):
    st.subheader("3. Áudio STT e Leitura Visual OCR (RF06 / RF08)")
    st.markdown("Transcreva áudios e leia documentos digitalizados. Confira os dados extraídos antes de encaminhar ao atendimento.")

    col_a, col_v = st.columns(2, gap="large")

    with col_a:
        st.markdown("##### Mensagem de Áudio (RF06)")
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
                st.text_area("Transcrição Revisada:", value=res_a.get("transcricao_revisada", ""), height=calcular_altura_dinamica(res_a.get("transcricao_revisada", ""), min_height=50), disabled=True)

                st.markdown("**Validação de Entidades Críticas:**")
                for c_nome, c_item in comp.get("detalhes", {}).items():
                    ok = c_item.get("localizado_na_transcricao")
                    icone = "[OK]" if ok else "[DIVERGÊNCIA]"
                    st.write(f"- {icone} **{c_nome.capitalize()}:** *{c_item.get('valor_esperado')}*")

                if st.button("Enviar Transcrição para Atendimento", width='stretch'):
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
                st.text_area("Texto Extraído pelo OCR:", value=txt_ocr, height=calcular_altura_dinamica(txt_ocr, min_height=50), disabled=True)

                if res_v.get("trechos_incertos_ou_ilegiveis"):
                    st.markdown("**Trechos Incertos / Manuscritos:**")
                    for t in res_v.get("trechos_incertos_ou_ilegiveis"):
                        st.caption(f"• `{t}`")

                if st.button("Enviar Texto OCR para Atendimento", width='stretch'):
                    st.session_state.solicitacao_texto = txt_ocr
                    st.session_state.solicitacao_caso = "visao_documento"
                    st.success("Texto transferido para o Módulo 1!")
            else:
                cod_erro = res_v.get("codigo_erro", "")
                msg_erro = res_v.get("erro", "Falha no processamento do OCR.")
                if cod_erro == "ocr_indisponivel":
                    st.warning(
                        "Aviso: Tesseract OCR não foi encontrado no sistema ou o pacote de idioma 'por' está ausente. "
                        "Como o motor local opera como fallback de último caso, para execução local instale o Tesseract-OCR "
                        "e o arquivo por.traineddata (ou execute o sistema via Docker, onde o Tesseract já está pré-instalado "
                        "e configurado). Alternativamente, configure as credenciais da OpenAI (GPT-4o Vision) ou OpenRouter no arquivo .env."
                    )
                else:
                    st.error(f"Erro no processamento OCR: {msg_erro}")


# ==============================================================================
# MÓDULO 4: Comunicação Visual Oficial (RF10)
# ==============================================================================
elif menu.startswith("4."):
    st.subheader("4. Comunicação Visual Institucional Híbrida (RF10)")
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

    texto_padrao_orientacoes = (
        "• INÍCIO DAS AULAS: 01 de Fevereiro de 2027 | Turno: Noturno (Carga Horária: 1.200h)\n"
        "• DOCUMENTOS: Apresentar RG, CPF e Comprovante de Residência para validação definitiva\n"
        "• FREQUÊNCIA: Presença obrigatória nos 10 primeiros dias letivos para garantia da vaga\n"
        "• ATENDIMENTO: Secretaria Escolar da ETEC Cuiabá | Portal: seciteci.mt.gov.br"
    )

    with st.container(border=True):
        st.markdown("##### Configuração da Peça Gráfica e Conteúdo Textual")
        col_t1, col_t2 = st.columns([1.5, 1], gap="medium")
        with col_t1:
            titulo_comunicado = st.text_input(
                "Título do Comunicado Oficial:",
                value="COMUNICADO OFICIAL: MATRÍCULAS E INGRESSO ETEC 2026",
                key="input_titulo_comunicado"
            )
        with col_t2:
            st.caption("Padrão institucional SECITECI-MT")
            st.markdown("*A ilustração central é gerada sem texto por IA; os textos oficiais são renderizados via Pillow com Brasão oficial.*")

        info_comunicado = st.text_area(
            "Informações e Orientações (painel abaixo da ilustração na arte):",
            value=texto_padrao_orientacoes,
            height=110,
            key="input_info_comunicado",
            help="Orientações oficiais que constarão no painel inferior da arte institucional."
        )

        c_btn1, c_btn2 = st.columns([1.2, 2])
        with c_btn1:
            if st.button("Gerar Comunicado Visual Oficial", type="primary", width='stretch'):
                with st.spinner("Gerando ilustração sem texto por IA e aplicando moldura GOV.MT com Brasão..."):
                    linhas = [l.strip() for l in info_comunicado.strip().split("\n") if l.strip()]
                    res_img = image_generator.gerar_comunicado_oficial(
                        titulo=titulo_comunicado,
                        orientacoes=linhas,
                        audit_logger=audit_logger
                    )
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

            # Campo de texto abaixo da imagem com as orientações (editável/copiável para publicação oficial)
            st.text_area(
                "Texto de Apoio / Legenda Oficial para Publicação:",
                value=st.session_state.get("input_info_comunicado", texto_padrao_orientacoes),
                height=110,
                key="texto_abaixo_imagem",
                help="Texto com as orientações oficiais para acompanhar a postagem nos canais institucionais."
            )

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
            st.markdown(f"**{meta.get('titulo') or 'Peça institucional'}**")
            with st.expander("Metadados e proveniência — RF10"):
                st.write(f"- **Dimensões:** {meta.get('dimensoes', '1080x1350')}")
                st.write(f"- **Modelo de IA:** `{meta.get('modelo_ia_utilizado')}`")
                st.write(f"- **Provedor:** `{meta.get('provedor_efetivo') or meta.get('provedor_solicitado')}`")
                st.write(f"- **Tarja:** `{meta.get('declaracao_proveniencia')}`")
                st.write(f"- **SHA-256:** `{meta.get('sha256_imagem', '')}`")

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
        st.info("Nenhuma peça visual gerada nesta sessão. Configure as informações acima e clique em **Gerar Comunicado Visual Oficial** para criar a peça institucional.")


# ==============================================================================
# MÓDULO 5: Auditoria & LGPD (RF11, RF12, RF13, RF21)
# ==============================================================================
elif menu.startswith("5."):
    st.subheader("5. Trilha de Auditoria, Segurança e Governança LGPD (RF11 a RF13, RF21)")
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
        st.markdown(
            """<style>
            /* Badges Destacados para Status de Decisão nos Expanders */
            [data-testid="stExpander"] summary span[style*="green"],
            [data-testid="stExpander"] summary span[style*="33, 195, 84"],
            [data-testid="stExpander"] summary span[style*="21, 128, 61"],
            [data-testid="stExpander"] summary span[style*="16a34a"] {
                background-color: #16A34A !important;
                color: #FFFFFF !important;
                padding: 3px 12px !important;
                border-radius: 12px !important;
                font-weight: 800 !important;
                font-size: 11px !important;
                display: inline-block !important;
                letter-spacing: 0.5px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
            }
            [data-testid="stExpander"] summary span[style*="red"],
            [data-testid="stExpander"] summary span[style*="255, 43, 43"],
            [data-testid="stExpander"] summary span[style*="220, 38, 38"],
            [data-testid="stExpander"] summary span[style*="dc2626"] {
                background-color: #DC2626 !important;
                color: #FFFFFF !important;
                padding: 3px 12px !important;
                border-radius: 12px !important;
                font-weight: 800 !important;
                font-size: 11px !important;
                display: inline-block !important;
                letter-spacing: 0.5px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
            }
            [data-testid="stExpander"] summary span[style*="orange"],
            [data-testid="stExpander"] summary span[style*="255, 170, 0"],
            [data-testid="stExpander"] summary span[style*="217, 119, 6"],
            [data-testid="stExpander"] summary span[style*="d97706"] {
                background-color: #D97706 !important;
                color: #FFFFFF !important;
                padding: 3px 12px !important;
                border-radius: 12px !important;
                font-weight: 800 !important;
                font-size: 11px !important;
                display: inline-block !important;
                letter-spacing: 0.5px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
            }
            [data-testid="stExpander"] summary span[style*="blue"],
            [data-testid="stExpander"] summary span[style*="37, 99, 235"],
            [data-testid="stExpander"] summary span[style*="0, 104, 201"],
            [data-testid="stExpander"] summary span[style*="2563eb"] {
                background-color: #2563EB !important;
                color: #FFFFFF !important;
                padding: 3px 12px !important;
                border-radius: 12px !important;
                font-weight: 800 !important;
                font-size: 11px !important;
                display: inline-block !important;
                letter-spacing: 0.5px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
            }
            [data-testid="stExpander"] summary span[style*="gray"],
            [data-testid="stExpander"] summary span[style*="grey"],
            [data-testid="stExpander"] summary span[style*="128, 128, 128"],
            [data-testid="stExpander"] summary span[style*="107, 114, 128"],
            [data-testid="stExpander"] summary span[style*="6b7280"] {
                background-color: #6B7280 !important;
                color: #FFFFFF !important;
                padding: 3px 12px !important;
                border-radius: 12px !important;
                font-weight: 800 !important;
                font-size: 11px !important;
                display: inline-block !important;
                letter-spacing: 0.5px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15) !important;
            }
            </style>""",
            unsafe_allow_html=True
        )

        logs_brutos = audit_logger.listar_execucoes()
        if not logs_brutos:
            st.info("Nenhum registro de auditoria gravado no momento.")
        else:
            # Consolida execuções (último estado prevalece para decisões humanas atualizadas)
            execucoes_map = {}
            for reg in logs_brutos:
                execucoes_map[reg.get("id_execucao")] = reg
            registros = list(reversed(list(execucoes_map.values())))

            # Agrupamento temporal
            agora = datetime.now()
            grupo_hoje = []
            grupo_semana = []
            grupo_anteriores = []

            for reg in registros:
                ts_str = reg.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.split("+")[0].split("Z")[0])
                    dias = (agora.date() - ts.date()).days
                    if dias == 0:
                        grupo_hoje.append(reg)
                    elif 1 <= dias <= 7:
                        grupo_semana.append(reg)
                    else:
                        grupo_anteriores.append(reg)
                except Exception:
                    grupo_anteriores.append(reg)

            total_aprov = sum(1 for r in registros if str(r.get("decisao_humana", {}).get("status", "")).upper() in ("APROVADO", "APROVADA"))
            total_pend = sum(1 for r in registros if str(r.get("decisao_humana", {}).get("status", "")).upper() in ("PENDENTE", "PENDENTE_REVISAO", "AGUARDANDO_VALIDACAO"))
            total_rej = sum(1 for r in registros if str(r.get("decisao_humana", {}).get("status", "")).upper() in ("REJEITADO", "REJEITADA"))

            # Indicadores de Topo (KPIs)
            kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
            kpi1.metric("Total de Registros", len(registros))
            kpi2.metric("Hoje", len(grupo_hoje))
            kpi3.metric("Esta Semana", len(grupo_semana))
            kpi4.metric("Anteriores", len(grupo_anteriores))
            kpi5.metric("Aprovadas", total_aprov)

            st.divider()

            # Filtros integrados
            f_col1, f_col2, f_col3 = st.columns([1.5, 1.5, 2])
            with f_col1:
                filtro_dec = st.selectbox(
                    "Filtrar por Status de Decisão:",
                    ["Todos os Status", "Aprovada", "Pendente de Revisão", "Revisar", "Rejeitada", "Não Aplicável"],
                    key="filtro_audit_decisao"
                )
            with f_col2:
                modalidades_disponiveis = ["Todas as Modalidades"] + sorted(list({str(r.get("modalidade", "")).lower() for r in registros if r.get("modalidade")}))
                filtro_mod = st.selectbox(
                    "Filtrar por Modalidade:",
                    modalidades_disponiveis,
                    key="filtro_audit_mod"
                )
            with f_col3:
                termo_busca = st.text_input(
                    "Buscar (ID, modelo, origem ou consulta):",
                    value="",
                    placeholder="Ex.: EXEC_20261029, gpt-4o, minuta...",
                    key="filtro_audit_termo"
                )

            def filtrar_lista(lista):
                resultado = []
                for r in lista:
                    dec_raw = r.get("decisao_humana", {})
                    st_val = str(dec_raw.get("status", "pendente")).upper() if isinstance(dec_raw, dict) else str(dec_raw).upper()
                    mod_val = str(r.get("modalidade", "")).lower()

                    if filtro_dec == "Aprovada" and st_val not in ("APROVADO", "APROVADA"):
                        continue
                    if filtro_dec == "Pendente de Revisão" and st_val not in ("PENDENTE", "PENDENTE_REVISAO", "AGUARDANDO_VALIDACAO"):
                        continue
                    if filtro_dec == "Rejeitada" and st_val not in ("REJEITADO", "REJEITADA"):
                        continue
                    if filtro_dec == "Revisar" and st_val not in ("REVISAR", "REVISÃO", "CORRIGIDO"):
                        continue
                    if filtro_dec == "Não Aplicável" and st_val not in ("NAO_APLICAVEL", "NÃO APLICÁVEL"):
                        continue

                    if filtro_mod != "Todas as Modalidades" and mod_val != filtro_mod:
                        continue

                    if termo_busca.strip():
                        tb = termo_busca.strip().lower()
                        conteudo_busca = f"{r.get('id_execucao', '')} {r.get('modelo', '')} {r.get('provedor', '')} {r.get('arquivo_origem', '')} {r.get('consulta', '')}".lower()
                        if tb not in conteudo_busca:
                            continue

                    resultado.append(r)
                return resultado

            def renderizar_itens(itens, sufixo_pag):
                itens_filtrados = filtrar_lista(itens)
                if not itens_filtrados:
                    st.info("Nenhum registro encontrado para os filtros selecionados.")
                    return

                col_p1, col_p2 = st.columns([1.2, 3])
                with col_p1:
                    limite_sel = st.selectbox(
                        "Exibir registros:",
                        [25, 50, 100, "Todos"],
                        index=0,
                        key=f"lim_{sufixo_pag}"
                    )
                with col_p2:
                    qtd_visivel = len(itens_filtrados) if limite_sel == "Todos" else min(len(itens_filtrados), int(limite_sel))
                    st.caption(f"Exibindo **{qtd_visivel}** de **{len(itens_filtrados)}** registros disponíveis neste período.")

                itens_exibir = itens_filtrados if limite_sel == "Todos" else itens_filtrados[:int(limite_sel)]

                for reg in itens_exibir:
                    exec_id = reg.get("id_execucao", "N/A")
                    mod = str(reg.get("modalidade", "")).upper()
                    dec = reg.get("decisao_humana", {})
                    status_raw = dec.get("status", "pendente") if isinstance(dec, dict) else str(dec)
                    dur = reg.get("duracao_segundos", 0.0)
                    ts_reg = reg.get("timestamp", "")
                    try:
                        dt_obj = datetime.fromisoformat(ts_reg.split("+")[0].split("Z")[0])
                        dt_formatada = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
                    except Exception:
                        dt_formatada = ts_reg[:19]

                    st_u = str(status_raw).upper()
                    if st_u in ("APROVADO", "APROVADA"):
                        bg_pill, txt_pill, borda_pill = "#16A34A", "#FFFFFF", "#15803D"
                        label_curta = "APROVADA"
                        bg_cor, borda_cor, txt_cor = "#DCFCE7", "#16A34A", "#15803D"
                        label_banner = "DECISÃO HUMANA: APROVADA"
                    elif st_u in ("REJEITADO", "REJEITADA"):
                        bg_pill, txt_pill, borda_pill = "#DC2626", "#FFFFFF", "#B91C1C"
                        label_curta = "REJEITADA"
                        bg_cor, borda_cor, txt_cor = "#FEE2E2", "#DC2626", "#B91C1C"
                        label_banner = "DECISÃO HUMANA: REJEITADA"
                    elif st_u in ("REVISAR", "REVISÃO", "CORRIGIDO"):
                        bg_pill, txt_pill, borda_pill = "#2563EB", "#FFFFFF", "#1D4ED8"
                        label_curta = "REVISAR"
                        bg_cor, borda_cor, txt_cor = "#DBEAFE", "#2563EB", "#1D4ED8"
                        label_banner = "DECISÃO HUMANA: REVISÃO SOLICITADA"
                    elif st_u in ("NAO_APLICAVEL", "NÃO APLICÁVEL"):
                        bg_pill, txt_pill, borda_pill = "#6B7280", "#FFFFFF", "#4B5563"
                        label_curta = "NÃO APLICÁVEL"
                        bg_cor, borda_cor, txt_cor = "#F3F4F6", "#6B7280", "#374151"
                        label_banner = "DECISÃO HUMANA: NÃO APLICÁVEL (EXECUÇÃO TÉCNICA)"
                    else:
                        bg_pill, txt_pill, borda_pill = "#D97706", "#FFFFFF", "#B45309"
                        label_curta = "PENDENTE"
                        bg_cor, borda_cor, txt_cor = "#FEF3C7", "#D97706", "#B45309"
                        label_banner = "DECISÃO HUMANA: PENDENTE DE REVISÃO"

                    with st.container(border=True):
                        c_b, c_i, c_d = st.columns([1.6, 6.4, 2])
                        with c_b:
                            st.markdown(
                                f'<div style="background-color:{bg_pill}; color:{txt_pill}; padding:4px 8px; border-radius:6px; font-weight:800; font-size:12px; text-align:center; letter-spacing:0.5px; border:1px solid {borda_pill};">{label_curta}</div>',
                                unsafe_allow_html=True
                            )
                        with c_i:
                            st.markdown(f"**[{mod}]** `{exec_id}` &nbsp;•&nbsp; <span style='color:#64748B; font-size:13px;'>{dt_formatada}</span>", unsafe_allow_html=True)
                        with c_d:
                            st.caption(f"Duração: **{dur:.2f}s**")

                        operador = dec.get("operador", "sistema") if isinstance(dec, dict) else "sistema"
                        data_dec = dec.get("data_decisao", dt_formatada) if isinstance(dec, dict) else dt_formatada
                        just = dec.get("justificativa", "Aguardando deliberação de servidor responsável.") if isinstance(dec, dict) else "Nenhuma"

                        with st.expander("Ver Detalhes do Registro e Trilha Técnica"):
                            st.markdown(
                                f"""<div style="background-color:{bg_cor}; border-left:5px solid {borda_cor}; padding:10px 14px; border-radius:4px; margin-bottom:12px;">
                                    <div style="font-size:13px; font-weight:800; color:{txt_cor}; letter-spacing:0.5px;">{label_banner}</div>
                                    <div style="font-size:12px; color:#374151; margin-top:4px;"><strong>Operador Responsável:</strong> {operador} &nbsp;|&nbsp; <strong>Data/Hora do Registro:</strong> {data_dec}</div>
                                    <div style="font-size:12px; color:#374151; margin-top:3px;"><strong>Justificativa Formal:</strong> {just}</div>
                                </div>""",
                                unsafe_allow_html=True
                            )

                            c_d1, c_d2 = st.columns(2)
                            with c_d1:
                                st.write(f"- **Origem:** `{reg.get('arquivo_origem', 'N/A')}`")
                                st.write(f"- **Provedor:** `{reg.get('provedor', 'N/A')}`")
                                st.write(f"- **Modelo IA:** `{reg.get('modelo', 'N/A')}`")
                                st.write(f"- **Duração:** `{dur:.3f} segundos`")
                            with c_d2:
                                st.write(f"- **Versão do Prompt:** `{reg.get('versao_prompt', 'N/A')}`")
                                st.write(f"- **Versão do Esquema:** `{reg.get('versao_esquema', '2.0.0')}`")
                                st.write(f"- **Versão do Índice Vetorial:** `{reg.get('versao_indice', 'N/A')}`")
                                st.write(f"- **Data/Hora Completa:** `{ts_reg}`")

                            if reg.get("ids_recuperados"):
                                st.write(f"- **IDs Recuperados (RAG):** `{', '.join(reg['ids_recuperados'])}`")
                            if reg.get("consulta"):
                                st.info(f"**Consulta / Texto de Entrada:** {reg['consulta']}")

            # Abas de agrupamento por período
            aba_h, aba_sem, aba_ant, aba_all = st.tabs([
                f"Hoje ({len(grupo_hoje)})",
                f"Esta Semana ({len(grupo_semana)})",
                f"Anteriores ({len(grupo_anteriores)})",
                f"Todas as Execuções ({len(registros)})"
            ])

            with aba_h:
                st.markdown("##### Execuções Registradas Hoje")
                renderizar_itens(grupo_hoje, "hoje")

            with aba_sem:
                st.markdown("##### Execuções Registradas nos Últimos 7 Dias")
                renderizar_itens(grupo_semana, "semana")

            with aba_ant:
                st.markdown("##### Execuções Registradas em Períodos Anteriores")
                renderizar_itens(grupo_anteriores, "anteriores")

            with aba_all:
                st.markdown("##### Visão Geral Completa de Todas as Execuções")
                renderizar_itens(registros, "todas")


# ==============================================================================
# MÓDULO 6: Assistente de Documentos RAG e Atendimento Integrado (RF17 a RF21)
# ==============================================================================
elif menu.startswith("6."):
    st.subheader("6. Assistente de Documentos Institucionais — RAG (RF18 a RF21)")
    st.caption("RAG · RF18 / RF19 / RF20 / RF21")
    st.markdown(
        "Consulta semântica fundamentada nos editais e retificações da ETEC/SECITECI-MT, com citações explícitas, "
        "detecção de conflitos normativos, separação entre fatos do solicitante e regras do acervo, e troca de provedor sem reconstrução do índice."
    )

    aba_consulta, aba_integrado = st.tabs([
        "Consulta ao acervo (RF18 / RF19 / RF21)",
        "Atendimento integrado (RF20)"
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
            escolha = st.selectbox("Perguntas do gabarito:", sugestoes)

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

            pergunta_digitada = st.text_input("Pergunta do cidadão:", value=pergunta_txt, placeholder="Digite a dúvida sobre o edital...")

        with c_cfg1:
            top_k = st.slider("Trechos (Top-K):", min_value=1, max_value=5, value=3)
        with c_cfg2:
            prov_rag = st.selectbox(
                "Provedor/Adaptador (RF21):",
                obter_provedores_disponiveis_rag(),
                format_func=lambda p: {
                    "extrator_fundamentado_local": "Extrator Local (Tolerância Zero à Alucinação)",
                    "openai": "OpenAI API (gpt-4o-mini / gpt-4o)",
                    "openrouter": "OpenRouter API",
                    "huggingface": "Hugging Face Inference",
                    "adaptador_simulado": "Adaptador Simulado (Demonstração T12)",
                }.get(p, p),
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
            st.markdown(f"**Pergunta consultada:** {res_c['pergunta']}")
            if resp.modo_geracao == "guardrail_entrada_bloqueado":
                st.error("SOLICITAÇÃO BLOQUEADA POR DIRETRIZES DE SEGURANÇA E ESCOPO (GUARDRAIL RF16)")
            elif resp.status == "fundamentada":
                st.success("RESPOSTA FUNDAMENTADA COM EVIDÊNCIA SUFICIENTE")
            elif resp.status == "conflito_de_fontes":
                st.error("CONFLITO DE FONTES DETECTADO (REVISÃO HUMANA OBRIGATÓRIA)")
            else:
                st.warning("SEM EVIDÊNCIA SUFICIENTE NO ACERVO (ABSTENÇÃO SEGURA)")

            # Renderização estruturada e legível da resposta e das fontes citadas
            linhas_resp = [l.strip() for l in resp.resposta.splitlines() if l.strip()]
            padrao_citacao = re.compile(r'^"(.+?)"\s*\[(.+)\]$')
            passagens_encontradas = []
            textos_gerais = []

            for l in linhas_resp:
                m = padrao_citacao.match(l)
                if m:
                    passagens_encontradas.append((m.group(1).strip(), m.group(2).strip()))
                else:
                    textos_gerais.append(l)

            if passagens_encontradas:
                if textos_gerais:
                    st.info("\n\n".join(textos_gerais))

                # 1. Resposta sintetizada do Assistente: somente para provedores LLM (OpenAI, etc.), omitida no Extrator Local
                if res_c.get("provedor") != "extrator_fundamentado_local":
                    st.markdown("##### Resposta do Assistente")
                    itens_sintese = []
                    for num_p, (cit, _) in enumerate(passagens_encontradas, start=1):
                        cit_limpa = cit.lstrip("- ").strip()
                        itens_sintese.append(f"• {cit_limpa}")
                    texto_resposta_montada = "\n\n".join(itens_sintese)
                    st.markdown(
                        f"<div style='background-color: #ffffff; border: 1.5px solid #2563eb; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-size: 1.02rem; line-height: 1.6; color: #0f172a;'>{texto_resposta_montada}</div>",
                        unsafe_allow_html=True
                    )
                    st.markdown(f"##### Citações e Fontes Normativas ({len(passagens_encontradas)})")
                else:
                    st.markdown(f"##### Fontes Normativas e Evidências Recuperadas ({len(passagens_encontradas)})")

                for num_p, (cit, metadado_fonte) in enumerate(passagens_encontradas, start=1):
                    cit_formatada = cit.lstrip("- ").strip()
                    st.markdown(
                        f"""<div style='background-color: #ffffff; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); opacity: 1.0;'>
                            <div style='font-size: 0.88rem; font-weight: 700; color: #1e3a8a; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;'>Trecho {num_p}:</div>
                            <div style='font-size: 1.04rem; font-weight: 600; color: #0f172a; line-height: 1.55; margin-bottom: 10px; opacity: 1.0;'>"{cit_formatada}"</div>
                            <div style='border-top: 1px solid #e2e8f0; padding-top: 8px; font-size: 0.86rem; color: #1e293b; opacity: 1.0;'>
                                <strong>📌 Fonte:</strong> <span style='color: #0369a1; font-weight: 500; opacity: 1.0;'>{metadado_fonte}</span>
                            </div>
                        </div>""",
                        unsafe_allow_html=True
                    )
            else:
                st.info(resp.resposta)

            if resp.divergencia_identificada:
                st.warning(f"**Divergência Normativa Identificada:** {resp.divergencia_identificada}")

            if resp.fontes:
                st.markdown("##### Trechos Recuperados no Acervo")
                st.caption(" • ".join(dict.fromkeys(
                    f"{t.documento_id} · versão {t.versao} · página {t.pagina or 1}" for t in resp.fontes
                )))
                for idx, t in enumerate(resp.fontes, start=1):
                    with st.expander(f"Documento {idx}: {t.documento_id} v{t.versao} (Pág. {t.pagina or '1'}) — Similaridade: {t.score_similaridade:.4f}"):
                        st.caption(f"ID: {t.trecho_id} | Seção: {t.secao or 'Geral'} | Distância: {t.score_distancia:.4f}")
                        st.markdown(
                            f"<div style='background-color: #ffffff; border: 1px solid #94a3b8; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 0.88rem; color: #0f172a; white-space: pre-wrap; line-height: 1.5; opacity: 1.0;'>{t.conteudo}</div>",
                            unsafe_allow_html=True
                        )
            else:
                st.caption("Nenhum trecho documental recuperado ou aplicável para esta resposta.")
            with st.expander("Detalhes da consulta — RF18 / RF21"):
                st.caption(f"Índice: `{res_c['versao_indice']}` | Adaptador: `{res_c['provedor']}`")

    with aba_integrado:
        st.caption("Solicitação → Extração e triagem → Evidência RAG → Minuta → Revisão humana → Auditoria")
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
                obter_provedores_disponiveis_rag(),
                format_func=lambda p: {
                    "extrator_fundamentado_local": "Extrator Local (Tolerância Zero à Alucinação)",
                    "openai": "OpenAI API (gpt-4o-mini / gpt-4o)",
                    "openrouter": "OpenRouter API",
                    "huggingface": "Hugging Face Inference",
                    "adaptador_simulado": "Adaptador Simulado (Demonstração T12)",
                }.get(p, p),
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
            texto_int = st.text_area("Texto da Solicitação:", value=texto_int_padrao, height=calcular_altura_dinamica(texto_int_padrao, min_height=70), key="txt_int_area")
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
                        inicio_atendimento = time.perf_counter()
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
                            duracao_segundos=time.perf_counter() - inicio_atendimento,
                        )
                        st.session_state.rag_atendimento_resultado = {
                            "id_execucao": exec_id_int,
                            "ficha": ficha_int,
                            "pacote": pacote_minuta,
                            "status_operador": "pendente",
                        }
                        st.session_state.estado_revisao_integrada = "pendente"

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

            with st.expander("Extração e triagem — RF14 / RF15"):
                c_lit, c_inf = st.columns(2)
                with c_lit:
                    st.markdown("###### Extração literal")
                    st.json(sep_i["extracao_literal"])
                with c_inf:
                    st.markdown("###### Informação inferida")
                    st.json(sep_i["informacao_inferida"])

            st.markdown("###### Evidências do acervo")
            for f_item in pacote_i.fontes:
                st.caption(
                    f"{f_item.documento_id} · versão {f_item.versao} · página {f_item.pagina or 1}"
                )
                with st.expander(f"Consultar trecho {f_item.trecho_id}"):
                    st.write(f_item.conteudo)
                    st.caption(f"Similaridade: {f_item.score_similaridade} | Distância: {f_item.score_distancia}")

            minuta_int_editada = st.text_area(
                "Minuta Institucional Fundamentada (Fatos do Solicitante + Regras do Acervo):",
                value=pacote_i.minuta_institucional or "",
                height=calcular_altura_dinamica(pacote_i.minuta_institucional or "", min_height=140),
                key="minuta_int_edit_area"
            )

            st.markdown("###### Decisão Humana sobre o Atendimento Integrado (RF20)")
            c_dec1, c_dec2 = st.columns([1, 2])
            with c_dec1:
                novo_status_op = st.selectbox(
                    "Estado da Revisão:",
                    ["pendente", "aprovada", "rejeitada", "revisar"],
                    key="estado_revisao_integrada",
                    format_func=lambda valor: {
                        "pendente": "Pendente", "aprovada": "Aprovar",
                        "rejeitada": "Rejeitar", "revisar": "Revisar",
                    }[valor],
                )
            with c_dec2:
                operador_int = st.text_input("Identificação do operador:", value="servidor_responsavel")
                just_op_int = st.text_input(
                    "Justificativa do Operador:",
                    value="Conferência dos trechos normativos e dados da ficha realizada pelo servidor."
                )

            st.caption("RF20 / RF21 · A decisão será registrada na auditoria deste atendimento.")
            assinatura = hashlib.sha256(json.dumps([
                res_int["id_execucao"], novo_status_op, operador_int, just_op_int, minuta_int_editada,
            ], ensure_ascii=False).encode("utf-8")).hexdigest()
            repetida = res_int.get("decisao_persistida_assinatura") == assinatura

            def solicitar_registro_decisao():
                st.session_state.registrando_decisao = True

            em_registro = st.session_state.get("registrando_decisao", False)
            st.button("Registrar decisão humana", width="stretch",
                      disabled=em_registro or repetida,
                      on_click=solicitar_registro_decisao)
            if em_registro:
                try:
                    with st.spinner("Registrando decisão..."):
                        if not repetida:
                            dec_validada = DecisaoOperador(
                                solicitacao_id=res_int["id_execucao"],
                                decisao=novo_status_op,
                                justificativa=just_op_int,
                                operador=operador_int,
                            )
                            salvo = audit_logger.atualizar_decisao_humana(
                                exec_id=dec_validada.solicitacao_id,
                                decisao=dec_validada.decisao.upper(),
                                justificativa=dec_validada.justificativa,
                                operador=dec_validada.operador,
                                texto_final=minuta_int_editada,
                            )
                            if not salvo:
                                raise ValueError("Confira a justificativa e o registro de origem.")
                            res_int["status_operador"] = novo_status_op
                            res_int["decisao_persistida_assinatura"] = assinatura
                            res_int["decisao_erro"] = None
                except ValueError as erro:
                    res_int["decisao_erro"] = f"A decisão não foi salva. {erro}"
                finally:
                    st.session_state.registrando_decisao = False
                st.rerun()
            if res_int.get("decisao_erro"):
                st.error(res_int["decisao_erro"])
            if res_int.get("decisao_persistida_assinatura"):
                st.success(f"Decisão persistida: {res_int['status_operador'].upper()} · Auditoria: {res_int['id_execucao']}")
                if repetida:
                    st.caption("Esta decisão já foi registrada. Altere a decisão, o texto ou a justificativa para registrar uma nova revisão.")


# ==============================================================================
# MÓDULO 7: Triagem & Ficha da Solicitação (RF14/RF15)
# ==============================================================================
elif menu.startswith("7."):
    st.subheader("7. Triagem e Ficha Estruturada da Solicitação (RF14 / RF15)")
    st.markdown("Informe a solicitação e confira o resumo, os dados extraídos e a triagem. A validação Pydantic separa os fatos do texto das informações inferidas.")

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
        escolha_sol = "Nova Manifestação"

    if (st.session_state.get("ficha_caso_carregado") != escolha_sol
            or "ficha_texto" not in st.session_state):
        st.session_state.ficha_caso_carregado = escolha_sol
        st.session_state.ficha_texto = caso_sol["texto_original"] if caso_sol else ""
        st.session_state.ficha_protocolo = (caso_sol.get("protocolo") or "") if caso_sol else ""
        st.session_state.ficha_data_externa = caso_sol.get("data") if caso_sol else None

    def limpar_envelope_da_ficha():
        # O envelope do exemplo pertence somente ao texto original carregado.
        st.session_state.ficha_protocolo = ""
        st.session_state.ficha_data_externa = None

    texto_f = st.text_area("Texto da Manifestação:", key="ficha_texto",
                          height=140, on_change=limpar_envelope_da_ficha)
    prot_f = st.text_input("Protocolo Externo (opcional):", key="ficha_protocolo")
    if caso_sol and texto_f != caso_sol["texto_original"]:
        st.caption("Texto editado: protocolo e data do exemplo foram descartados. Informe um novo protocolo apenas se houver.")

    if st.button("Processar Ficha Pydantic", type="primary"):
        if not texto_f.strip():
            st.warning("Informe o texto.")
        else:
            with st.spinner("Processando ficha estruturada..."):
                exemplo_intacto = bool(caso_sol and texto_f == caso_sol["texto_original"])
                protocolo_atual = prot_f.strip() or None
                # Valide também na entrada do processamento: um evento tardio
                # do widget não pode reintroduzir o envelope do exemplo editado.
                if (caso_sol and not exemplo_intacto
                        and protocolo_atual == (caso_sol.get("protocolo") or "").strip()):
                    protocolo_atual = None
                ficha = processar_solicitacao(
                    texto_f,
                    protocolo_externo=protocolo_atual,
                    data_externa=(st.session_state.ficha_data_externa if exemplo_intacto else None),
                )
                dados_ui = ficha.para_interface_usuario()
                separado = ficha.separar_literal_e_inferido()

                f1, f2, f3 = st.columns(3)
                f1.metric("Categoria", ficha.categoria)
                f2.metric("Campos Ausentes", len(ficha.campos_ausentes))
                f3.metric("Necessita Revisão?", "SIM" if ficha.necessidade_revisao else "NÃO")

                st.info(f"**Resumo Fiel (até 100 palavras):**\n\n{ficha.resumo}")

                with st.expander("Dados extraídos e triagem — RF14 / RF15"):
                    col_l, col_i = st.columns(2)
                    with col_l:
                        st.markdown("##### Extração literal (dados do texto)")
                        st.json(separado["extracao_literal"])
                    with col_i:
                        st.markdown("##### Informação inferida (triagem)")
                        st.json(separado["informacao_inferida"])

                with st.expander("Ficha completa para exibição (campos ausentes: 'não localizado')"):
                    st.json(dados_ui)


# ==============================================================================
# MÓDULO 8: Painel de Sentimentos (RF22)
# ==============================================================================
elif menu.startswith("8."):
    st.subheader("8. Painel Analítico de Avaliações e Sentimento do Cidadão (RF22)")
    st.markdown(
        "Avaliações positivas, negativas, neutras e indeterminadas, "
        "com filtros por categoria e período. As contagens são calculadas sem duplicar avaliações."
    )

    p_av = resolver_caminho("dados/avaliacoes/avaliacoes_atendimento.json")
    if p_av.exists():
        with open(p_av, "r", encoding="utf-8") as fa:
            avaliacoes = json.load(fa)

        categorias_disp = ["Todas"] + sorted(list({a.get("categoria_servico", "Geral") for a in avaliacoes if a.get("categoria_servico")}))

        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            cat_filtro = st.selectbox("Filtrar por Categoria/Canal:", categorias_disp)
        with cf2:
            d_ini = st.date_input(
                "Data Inicial:",
                value=date(2026, 6, 1),
                format="DD/MM/YYYY",
                help="Data de início do recorte temporal (padrão amplo cobrindo todo o exercício de 2026)."
            )
            dt_ini = d_ini.strftime("%Y-%m-%d") if d_ini else None
        with cf3:
            d_fim = st.date_input(
                "Data Final:",
                value=date(2026, 12, 31),
                format="DD/MM/YYYY",
                help="Data final do recorte temporal (padrão amplo cobrindo todo o exercício de 2026)."
            )
            dt_fim = d_fim.strftime("%Y-%m-%d") if d_fim else None

        if d_ini and d_fim and d_ini > d_fim:
            st.error("A Data Inicial não pode ser posterior à Data Final. Por favor, ajuste o período.")
            avaliacoes_filtradas = []
        else:
            avaliacoes_filtradas = filtrar_e_deduplicar_avaliacoes(
                avaliacoes,
                categoria_servico=cat_filtro,
                data_inicio=dt_ini,
                data_fim=dt_fim,
            )

        classificacoes = [classificar_sentimento_avaliacao(a["id"], a["texto"]) for a in avaliacoes_filtradas]
        agregacao = agregar_sentimentos_determinístico(classificacoes)

        periodo_txt = f"{d_ini.strftime('%d/%m/%Y')} até {d_fim.strftime('%d/%m/%Y')}" if (d_ini and d_fim) else "Período Completo"
        st.markdown(
            f"<div style='color: #334155; font-size: 0.9rem; margin-bottom: 0.6rem;'>"
            f"<strong>Recorte Temporal Ativo:</strong> <code>{periodo_txt}</code> | "
            f"<strong>Denominador Visível da Consulta Atual:</strong> <code>{agregacao['denominador']}</code> avaliações únicas consideradas."
            f"</div>",
            unsafe_allow_html=True
        )

        if agregacao["denominador"] == 0:
            st.warning("Nenhuma avaliação encontrada para o período e a categoria selecionados.")
        else:
            col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
            with col_s1:
                with st.container(border=True):
                    st.metric("Total Único", agregacao["denominador"], help="Denominador de avaliações únicas no filtro ativo")
                    st.markdown("<div style='color: #334155; font-size: 0.85rem; font-weight: 500;'>Avaliações no filtro</div>", unsafe_allow_html=True)
            with col_s2:
                with st.container(border=True):
                    st.metric("Positivas", agregacao["distribuicao"]["positiva"])
                    st.markdown(f"<div style='color: #166534; font-size: 0.85rem; font-weight: 600;'>{agregacao['percentuais']['positiva']}% do total</div>", unsafe_allow_html=True)
            with col_s3:
                with st.container(border=True):
                    st.metric("Negativas", agregacao["distribuicao"]["negativa"])
                    st.markdown(f"<div style='color: #991b1b; font-size: 0.85rem; font-weight: 600;'>{agregacao['percentuais']['negativa']}% do total</div>", unsafe_allow_html=True)
            with col_s4:
                with st.container(border=True):
                    st.metric("Neutras", agregacao["distribuicao"]["neutra"])
                    st.markdown(f"<div style='color: #334155; font-size: 0.85rem; font-weight: 600;'>{agregacao['percentuais']['neutra']}% do total</div>", unsafe_allow_html=True)
            with col_s5:
                with st.container(border=True):
                    st.metric("Indeterminadas", agregacao["distribuicao"]["indeterminada"], help="Casos com necessidade de revisão")
                    st.markdown(f"<div style='color: #9a3412; font-size: 0.85rem; font-weight: 600;'>{agregacao['percentuais']['indeterminada']}% do total</div>", unsafe_allow_html=True)

            df_barras = pd.DataFrame([
                {"Sentimento": "Positiva", "Quantidade": agregacao["distribuicao"]["positiva"]},
                {"Sentimento": "Negativa", "Quantidade": agregacao["distribuicao"]["negativa"]},
                {"Sentimento": "Neutra", "Quantidade": agregacao["distribuicao"]["neutra"]},
                {"Sentimento": "Indeterminada", "Quantidade": agregacao["distribuicao"]["indeterminada"]},
            ])

            grafico_sentimento = (
                alt.Chart(df_barras)
                .mark_bar(cornerRadius=4)
                .encode(
                    x=alt.X(
                        "Sentimento:N",
                        title=None,
                        sort=["Positiva", "Negativa", "Neutra", "Indeterminada"],
                        axis=alt.Axis(
                            labelAngle=0,
                            labelColor="#334155",
                            labelFontSize=13,
                            labelFontWeight="bold",
                        )
                    ),
                    y=alt.Y(
                        "Quantidade:Q",
                        title="Quantidade de Avaliações",
                        axis=alt.Axis(
                            labelColor="#334155",
                            titleColor="#334155",
                            labelFontSize=11,
                            tickMinStep=1,
                        )
                    ),
                    color=alt.Color(
                        "Sentimento:N",
                        scale=alt.Scale(
                            domain=["Positiva", "Negativa", "Neutra", "Indeterminada"],
                            range=["#15803d", "#b91c1c", "#475569", "#c2410c"]
                        ),
                        legend=None
                    ),
                    tooltip=["Sentimento", "Quantidade"]
                )
                .properties(height=280)
            )
            st.altair_chart(grafico_sentimento, width="stretch")
            st.markdown(f"<div style='color: #475569; font-size: 0.82rem;'><strong>Nota Metodológica:</strong> {agregacao['nota_metodologica']}</div>", unsafe_allow_html=True)

            with st.expander("Detalhes do prompt de sentimento (RF22)"):
                st.code(montar_prompt_sentimento_isolado(avaliacoes_filtradas[0]["texto"]), language="xml")

            st.markdown("##### Avaliações dos cidadãos")
            for av, cl in zip(avaliacoes_filtradas, classificacoes):
                with st.expander(f"{cl.id} [{av.get('categoria_servico', 'Geral')} | {av.get('data', '')}] — [{cl.polaridade.upper()}] — {av['texto'][:60]}..."):
                    st.write(f"**Texto:** {av['texto']}")
                    st.write(f"**Justificativa:** {cl.justificativa}")
                    st.caption(f"Confiança Estimada: {cl.confianca_estimada:.2f} | Requer Revisão: {cl.necessidade_revisao}")


# ==============================================================================
# MÓDULO 9: Gestão do Acervo e Expurgo Vetorial (RF24)
# ==============================================================================
elif menu.startswith("9."):
    st.subheader("9. Gestão do Acervo, Governança e Expurgo Vetorial (RF17 / RF24)")
    st.markdown("Gerencie a seleção de documentos e sua recuperação. As fontes e evidências históricas são preservadas; a exclusão abaixo remove os vetores ativos.")
    arquivos_acervo = sorted(str(p) for p in resolver_caminho("dados/acervo").iterdir() if p.suffix.lower() in {".txt", ".pdf"})
    selecionados = st.multiselect("Documentos para recriar o índice:", arquivos_acervo, default=arquivos_acervo,
                                 format_func=lambda p: Path(p).name)
    st.caption("Recriar usa somente os documentos selecionados e pode reincluir um documento antes excluído. Nenhum PDF original é alterado.")
    if st.button("Recriar índice dos documentos selecionados"):
        if not selecionados:
            st.warning("Selecione ao menos um documento.")
        else:
            novo_indice = IndiceVetorial(caminho_indice=None, persistir=False)
            for arquivo in selecionados:
                novo_indice.adicionar_chunks(dividir_em_chunks(ler_arquivo(arquivo), configuracao="A"))
            novo_indice.caminho_indice = indice_vetorial.caminho_indice
            novo_indice.salvar()
            obter_indice_vetorial.clear()
            st.success("Índice recriado com fontes e metadados atualizados.")
            st.rerun()

    docs_presentes = sorted(list({c["documento_id"] for c in indice_vetorial.chunks}))
    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("Documentos Ativos no Acervo", len(docs_presentes))
    c_m2.metric("Total de Chunks Indexados", len(indice_vetorial.chunks))
    c_m3.metric("Versão Atual do Índice", indice_vetorial.versao_indice)

    st.markdown("##### Documentos ativos e evidências indexadas")
    for d in docs_presentes:
        chunks_d = [c for c in indice_vetorial.chunks if c["documento_id"] == d]
        titulo_doc = chunks_d[0].get("titulo", d) if chunks_d else d
        qtd = len(chunks_d)

        with st.expander(f"{d} — {titulo_doc} ({qtd} trechos indexados)"):
            st.caption(f"Natureza: {chunks_d[0].get('natureza', 'não classificada')} | Origem: {chunks_d[0].get('fonte_original', 'não classificada')}")
            for c in chunks_d:
                t_id = c.get("trecho_id", "")
                p = c.get("pagina", 1)
                sec = c.get("secao", "Geral")
                conteudo = c.get("conteudo", "").strip()
                st.markdown(f"**Trecho:** `{t_id}` | **Página:** `{p}` | **Seção:** `{sec}`")
                st.text_area(f"Conteúdo do trecho {t_id}", value=conteudo, height=calcular_altura_dinamica(conteudo, min_height=40), disabled=True, label_visibility="collapsed")

    st.divider()
    st.markdown("##### Exclusão da recuperação ativa (RF24)")
    st.caption("Remove os chunks e vetores do índice. Fontes e resultados históricos permanecem como evidência, conforme a política de retenção documentada.")
    doc_sel = st.selectbox("Selecione o documento para expurgo definitivo:", docs_presentes if docs_presentes else ["Nenhum"])

    if st.button("Excluir e Expurgar Fragmentos Definitivamente", type="secondary"):
        if doc_sel and doc_sel != "Nenhum":
            removidos = indice_vetorial.excluir_documento(doc_sel)
            audit_logger.registrar_execucao(
                modalidade="exclusao_indice", arquivo_origem=doc_sel, provedor="local", modelo="indice",
                versao_prompt="governanca_v3", parametros={}, resultado={"documento_id": doc_sel, "chunks_removidos": removidos},
                duracao_segundos=0, versao_indice=indice_vetorial.versao_indice)
            st.success(f"Documento '{doc_sel}' excluído com sucesso! {removidos} fragmentos removidos definitivamente do índice.")
            st.rerun()

# ==============================================================================
# MÓDULO 10: Matriz de Testes Automatizados T01 a T15 (RF23 / RF24)
# ==============================================================================
elif menu.startswith("10."):
    st.subheader("10. Central de Avaliação e Testes Automatizados (T01 a T15 — RF23 / RF24)")
    st.caption("Matriz T01–T15 · RF23 / RF24")
    st.markdown(
        "Ambiente interativo de execução de testes em tempo real: execute a matriz contratual de 15 cenários (`T01` a `T15`), "
        "dispare asserções individuais sob demanda ou execute a suíte oficial do `pytest` com captura de terminal ao vivo."
    )

    caminho_rel_d02 = resolver_caminho("resultados/metricas/relatorio_avaliacao_d02.json")

    mapa_testes_desc = {
        "T01": "T01 — RF14: Esquema Pydantic, Campos Ausentes e Chaves Extras",
        "T02": "T02 — RF14: Bloqueio de Data Impossível e Alucinação Factual",
        "T03": "T03 — RF15: Classificação e Omissões nas 6 Solicitações",
        "T04": "T04 — RF16: Defesas Adversariais (ADV-01 Injeção Direta, ADV-02 Corpus, ADV-03 Segredo)",
        "T05": "T05 — RF16: Bloqueio Fora de Escopo, Arquivo Excessivo e Limite de Chamadas",
        "T06": "T06 — RF17: Indexação dos 6 Documentos, Recarga e Deduplicação",
        "T07": "T07 — RF18: Recuperação Vetorial Top-3 e Chunking (A: 400/80 vs B: 800/150)",
        "T08": "T08 — RF19: 5 Perguntas Respondíveis (P1 a P5) com Citação Documental",
        "T09": "T09 — RF19: 2 Perguntas sem Resposta (P6 e P7) com Abstenção Explícita",
        "T10": "T10 — RF19: Detecção de Fontes Contraditórias (P8: DOC-004 vs DOC-006)",
        "T11": "T11 — RF20: Fluxo Assistente Completo (Solicitação, RAG, Minuta e Revisão Humana)",
        "T12": "T12 — RF21: Segunda Configuração de Geração e Falha Simulada sem Reconstruir Índice",
        "T13": "T13 — RF22: Classificação das 12 Avaliações, Deduplicação e Zero-Division",
        "T14": "T14 — RF24: Expurgo Vetorial Definitivo e Direito ao Esquecimento",
        "T15": "T15 — RF23: Regressão dos Fluxos D01 e Acessibilidade TTS para Ausências",
    }

    # Painel de Disparo de Testes ao Vivo
    with st.container(border=True):
        st.markdown("##### Central de Disparo de Testes ao Vivo")
        col_ctrl1, col_ctrl2 = st.columns([1.2, 1.8], gap="medium")

        with col_ctrl1:
            st.markdown("**Bateria Contratual Completa (T01 a T15):**")
            executar_todos = st.button("Executar Todos os Testes (T01 a T15) ao Vivo", type="primary", use_container_width=True)

        with col_ctrl2:
            st.markdown("**Execução de Teste Específico sob Demanda:**")
            col_sel, col_btn_ind = st.columns([2.5, 1.2])
            with col_sel:
                teste_escolhido = st.selectbox(
                    "Selecione o cenário para testar na hora:",
                    list(mapa_testes_desc.keys()),
                    format_func=lambda k: mapa_testes_desc[k],
                    label_visibility="collapsed"
                )
            with col_btn_ind:
                executar_individual = st.button("Executar Teste", type="secondary", use_container_width=True)

    # Execução de Teste Individual
    if executar_individual:
        with st.spinner(f"Executando asserções reais do teste {teste_escolhido}..."):
            avaliador = AvaliadorDesafio02(indice=indice_vetorial)
            res_ind = avaliador.executar_teste_individual(teste_escolhido)
            st.session_state.teste_individual_resultado = res_ind

    if st.session_state.teste_individual_resultado:
        ind = st.session_state.teste_individual_resultado
        st_ok = (ind.get("status") == "APROVADO")
        with st.container(border=True):
            st.markdown(f"##### Resultado da Execução Individual: `{ind.get('teste')}` ({ind.get('requisito')})")
            c_ind1, c_ind2, c_ind3 = st.columns([1, 1, 3])
            c_ind1.metric("Status", ind.get("status"))
            c_ind2.metric("Tempo de Execução", f"{ind.get('duracao_ms', 0):.2f} ms")
            c_ind3.markdown(f"**Cenário Testado:**\n\n{ind.get('cenario')}")
            with st.expander("Evidências das asserções", expanded=not st_ok):
                if isinstance(ind.get("evidencia"), dict):
                    st.json(ind.get("evidencia"))
                elif isinstance(ind.get("evidencia"), list):
                    for ev in ind.get("evidencia"):
                        st.write(f"- `{ev}`")
                else:
                    st.info(str(ind.get("evidencia")))

    # Execução da Matriz Completa
    if executar_todos:
        avaliador = AvaliadorDesafio02(indice=indice_vetorial)
        lista_resultados = []
        barra = st.progress(0, text="Iniciando execução da matriz de testes...")

        with st.status("Executando bateria de 15 testes contratuais em tempo real...", expanded=True) as status_box:
            codigos = [f"T{i:02d}" for i in range(1, 16)]
            for i, cod in enumerate(codigos, 1):
                status_box.write(f"Executando `{cod}`...")
                t_res = avaliador.executar_teste_individual(cod)
                lista_resultados.append(t_res)
                stt_label = "APROVADO" if t_res["status"] == "APROVADO" else "FALHOU"
                status_box.write(f"[{stt_label}] **{cod}** ({t_res['requisito']}) — {t_res['cenario']} ({t_res.get('duracao_ms', 0):.2f}ms)")
                barra.progress(i / len(codigos), text=f"Progresso: {i}/15 testes concluídos ({cod})")

            res_nlp = avaliador.avaliar_solicitacoes_nlp()
            res_chunking = avaliador.avaliar_recuperacao_chunking()
            res_rag = avaliador.avaliar_rag_completo()
            res_sent = avaliador.avaliar_sentimentos()
            duracao_total = round(sum(m.get("duracao_ms", 0) for m in lista_resultados), 2)

            relatorio_ao_vivo = {
                "timestamp": datetime.now().isoformat(),
                "origem": "execucao_ao_vivo_usuario",
                "total_testes": len(lista_resultados),
                "aprovados": sum(1 for m in lista_resultados if m["status"] == "APROVADO"),
                "duracao_total_ms": duracao_total,
                "resumo_metricas": {
                    "nlp_solicitacoes": {
                        "acuracia_categoria": res_nlp["acuracia_categoria"],
                        "total_omissoes": res_nlp["total_omissoes"],
                        "total_fatos_sem_suporte": res_nlp["total_fatos_sem_suporte"],
                    },
                    "chunking_recuperacao": res_chunking["comparativo_configs"],
                    "rag_8_perguntas": {
                        "taxa_acerto_status": res_rag["taxa_acerto_status"],
                        "taxa_acerto_citacao": res_rag["taxa_acerto_citacao"],
                    },
                    "sentimentos_12_avaliacoes": {
                        "taxa_acerto": res_sent["taxa_acerto"],
                        "distribuicao": res_sent["agregacao"]["distribuicao"],
                    },
                },
                "matriz": lista_resultados,
            }

            try:
                os.makedirs("resultados/metricas", exist_ok=True)
                with open("resultados/metricas/relatorio_avaliacao_d02.json", "w", encoding="utf-8") as f_rel:
                    json.dump(relatorio_ao_vivo, f_rel, indent=2, ensure_ascii=False)
            except OSError:
                pass

            st.session_state.testes_ao_vivo = relatorio_ao_vivo
            status_box.update(label=f"Bateria concluída: {relatorio_ao_vivo['aprovados']}/15 aprovados em {duracao_total:.2f}ms!", state="complete", expanded=False)

    # Dados a exibir na interface
    if st.session_state.testes_ao_vivo:
        rel_ativo = st.session_state.testes_ao_vivo
        tag_origem = "Executado ao Vivo nesta Sessão"
    elif caminho_rel_d02.exists():
        rel_ativo = json.loads(caminho_rel_d02.read_text(encoding="utf-8"))
        tag_origem = "Último Relatório em Disco"
    else:
        rel_ativo = None
        tag_origem = "Nenhuma Execução Realizada"

    if not rel_ativo:
        st.info("Nenhuma execução de testes registrada. Utilize o painel acima para executar a bateria contratual ou rodar o pytest.")
    else:
        testes_lista = rel_ativo.get("matriz") or rel_ativo.get("resumo_matriz", {}).get("testes", [])
        total_testes = rel_ativo.get("total_testes", len(testes_lista))
        aprovados = rel_ativo.get("aprovados", sum(1 for t in testes_lista if t.get("status") == "APROVADO"))
        reprovados = total_testes - aprovados
        taxa = (aprovados / total_testes * 100) if total_testes else 0.0

        ts_raw = rel_ativo.get("timestamp", "")
        if ts_raw:
            try:
                dt = datetime.fromisoformat(ts_raw)
                ts_formatado = dt.strftime("%d/%m/%Y às %H:%M:%S")
            except Exception:
                ts_formatado = ts_raw
        else:
            ts_formatado = "Não registrado"

        dur_tot_ms = rel_ativo.get("duracao_total_ms")
        dur_txt = f"{dur_tot_ms:.1f} ms" if dur_tot_ms else "—"

        k1, k2, k3 = st.columns(3)
        k1.metric("Total de Testes", total_testes)
        k2.metric("Aprovados", f"{aprovados} / {total_testes}")
        k3.metric("Taxa de Sucesso", f"{taxa:.1f}%")
        k4, k5 = st.columns([1, 2])
        with k4:
            st.markdown("**Duração da bateria**")
            st.write(dur_txt)
        with k5:
            st.markdown("**Origem dos dados**")
            st.write(tag_origem)
            st.caption(f"Relatório de {ts_formatado}")

        st.divider()

        tab_t_cards, tab_t_pytest, tab_t_chunking, tab_t_raw = st.tabs([
            "1. Resultados da Matriz Contratual (T01 a T15)",
            "2. Terminal Pytest Oficial (Execução em Tempo Real)",
            "3. Comparativo Experimental de Chunking (RF18)",
            "4. Relatório Estruturado e Evidências Fatuais (JSON)",
        ])

        with tab_t_cards:
            st.markdown("##### Resultados por teste")
            f_col1, f_col2, f_col3 = st.columns([1, 1, 2])

            with f_col1:
                filtro_status = st.selectbox(
                    "Filtrar por Status:",
                    ["Todos", "Apenas Aprovados", "Apenas Reprovados"],
                    key="filtro_status_testes"
                )
            with f_col2:
                reqs = sorted(list({t.get("requisito", "") for t in testes_lista if t.get("requisito")}))
                filtro_req = st.selectbox("Filtrar por Requisito:", ["Todos"] + reqs, key="filtro_req_testes")

            with f_col3:
                filtro_busca = st.text_input("Buscar teste por texto (ex.: T01, SQL, chunking, P6):", key="filtro_busca_testes")

            testes_exibicao = []
            for t in testes_lista:
                stt = t.get("status", "")
                if filtro_status == "Apenas Aprovados" and stt != "APROVADO":
                    continue
                if filtro_status == "Apenas Reprovados" and stt == "APROVADO":
                    continue
                if filtro_req != "Todos" and t.get("requisito") != filtro_req:
                    continue
                if filtro_busca.strip():
                    termo = filtro_busca.strip().lower()
                    texto_busca = f"{t.get('teste', '')} {t.get('requisito', '')} {t.get('cenario', '')} {json.dumps(t.get('evidencia', ''))}".lower()
                    if termo not in texto_busca:
                        continue
                testes_exibicao.append(t)

            st.caption(f"Exibindo {len(testes_exibicao)} de {len(testes_lista)} testes contratuais.")

            for t in testes_exibicao:
                t_id = t.get("teste", "T??")
                t_req = t.get("requisito", "RF??")
                t_cenario = t.get("cenario", "")
                t_status = t.get("status", "PENDENTE")
                t_ms = t.get("duracao_ms")
                tempo_str = f" • {t_ms:.1f}ms" if t_ms is not None else ""
                is_aprovado = (t_status == "APROVADO")

                titulo_expander = f"[{t_id}] • {t_status} • {t_req} — {t_cenario}{tempo_str}"

                with st.expander(titulo_expander, expanded=(not is_aprovado)):
                    col_det1, col_det2 = st.columns([3, 1])
                    with col_det1:
                        st.markdown(f"**Identificador:** `{t_id}` | **Requisito Contratual:** `{t_req}`")
                        st.markdown(f"**Cenário Avaliado:**\n\n{t_cenario}")
                    with col_det2:
                        if is_aprovado:
                            st.success(f"Status: {t_status}")
                        else:
                            st.error(f"Status: {t_status}")
                        if t_ms is not None:
                            st.caption(f"Tempo de execução: **{t_ms:.2f} ms**")

                    st.markdown("**Evidência Factual Registrada:**")
                    evid = t.get("evidencia")

                    if isinstance(evid, dict):
                        col_ev1, col_ev2 = st.columns(2)
                        itens_ev = list(evid.items())
                        metade = (len(itens_ev) + 1) // 2
                        with col_ev1:
                            for k, v in itens_ev[:metade]:
                                st.markdown(f"- **{k}:** `{v}`")
                        with col_ev2:
                            for k, v in itens_ev[metade:]:
                                st.markdown(f"- **{k}:** `{v}`")
                    elif isinstance(evid, list):
                        for item in evid:
                            st.markdown(f"- `{item}`")
                    else:
                        st.info(str(evid))

        with tab_t_pytest:
            st.markdown("##### Execução da Suíte Oficial Pytest no Terminal")
            st.markdown(
                "Dispara o executável real do `pytest` no ambiente Python local, testando arquivos de teste unitário e de integração "
                "com captura direta do console, contagem de asserções e tempo decorrido."
            )

            opcoes_pytest = {
                "testes/test_desafio02_rf14_rf24.py": "1. Testes do Desafio 02 (15 testes contratuais — RF14 a RF24)",
                "testes/test_sistema.py": "2. Regressão Geral do Sistema (test_sistema.py)",
                "testes/test_integracao_main.py": "3. Pipeline de Integração e CLI (test_integracao_main.py)",
                "testes/": "4. Suíte Completa do Repositório (todos os 318 testes — D01 + D02)",
            }

            col_py1, col_py2 = st.columns([2.5, 1])
            with col_py1:
                alvo_pytest = st.selectbox(
                    "Selecione a suíte pytest a executar:",
                    list(opcoes_pytest.keys()),
                    format_func=lambda k: opcoes_pytest[k],
                    key="sel_alvo_pytest"
                )
            with col_py2:
                st.write("")
                st.write("")
                btn_rodar_pytest = st.button("Executar Pytest no Terminal", type="primary", use_container_width=True)

            if btn_rodar_pytest:
                with st.spinner(f"Executando pytest em `{alvo_pytest}`..."):
                    t_py_ini = time.perf_counter()
                    cmd = [sys.executable, "-m", "pytest", alvo_pytest, "-v"]
                    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                    t_py_fim = time.perf_counter()
                    st.session_state.pytest_resultado = {
                        "alvo": alvo_pytest,
                        "exit_code": proc.returncode,
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                        "duracao_s": round(t_py_fim - t_py_ini, 2),
                    }

            if st.session_state.pytest_resultado:
                py_res = st.session_state.pytest_resultado
                c_py_k1, c_py_k2, c_py_k3 = st.columns(3)
                if py_res["exit_code"] == 0:
                    c_py_k1.success("Resultado: SUCESSO (código de saída 0)")
                else:
                    c_py_k1.error(f"Resultado: FALHA (código de saída {py_res['exit_code']})")
                c_py_k2.metric("Tempo Total", f"{py_res['duracao_s']:.2f} s")
                c_py_k3.metric("Arquivo Executado", py_res["alvo"].split("/")[-1])

                st.markdown("**Saída Real do Console Pytest:**")
                st.code(py_res["stdout"] if py_res["stdout"] else py_res["stderr"], language="bash")

        with tab_t_chunking:
            st.markdown("##### Comparativo Experimental de Recuperação Vetorial (RF18 / T07)")
            st.markdown("Avaliação de sensibilidade das duas estratégias de fatiamento de documentos sobre as perguntas respondíveis do gabarito oficial.")

            chunk_data = rel_ativo.get("resumo_metricas", {}).get("chunking_recuperacao", {})
            cfg_a = chunk_data.get("config_a", {})
            cfg_b = chunk_data.get("config_b", {})

            col_cfg_a, col_cfg_b = st.columns(2)
            with col_cfg_a:
                st.info(
                    "**Configuração A (Granularidade Alta)**\n\n"
                    "- **Tamanho do Chunk:** 400 caracteres\n"
                    "- **Sobreposição (Overlap):** 80 caracteres\n"
                    f"- **Total de Chunks:** `{cfg_a.get('total_chunks', 49)} trechos`\n"
                    f"- **Taxa de Acerto (Top-3):** `{cfg_a.get('percentual', '100.0%')}` ({cfg_a.get('numerador', 5)}/{cfg_a.get('denominador', 5)})"
                )

            with col_cfg_b:
                st.info(
                    "**Configuração B (Contexto Amplo)**\n\n"
                    "- **Tamanho do Chunk:** 800 caracteres\n"
                    "- **Sobreposição (Overlap):** 150 caracteres\n"
                    f"- **Total de Chunks:** `{cfg_b.get('total_chunks', 24)} trechos`\n"
                    f"- **Taxa de Acerto (Top-3):** `{cfg_b.get('percentual', '100.0%')}` ({cfg_b.get('numerador', 5)}/{cfg_b.get('denominador', 5)})"
                )

            detalhes_a = {item["id"]: item for item in cfg_a.get("detalhes", [])}
            detalhes_b = {item["id"]: item for item in cfg_b.get("detalhes", [])}

            tabela_comp = []
            for pid in sorted(list(set(detalhes_a.keys()) | set(detalhes_b.keys()))):
                it_a = detalhes_a.get(pid, {})
                it_b = detalhes_b.get(pid, {})
                tabela_comp.append({
                    "Pergunta ID": pid,
                    "Enunciado": it_a.get("pergunta", it_b.get("pergunta", "")),
                    "Doc Esperado": ", ".join(it_a.get("docs_esperados", [])),
                    "Recuperado Config A (400/80)": ", ".join(it_a.get("docs_recuperados", [])[:2]),
                    "Recuperado Config B (800/150)": ", ".join(it_b.get("docs_recuperados", [])[:2]),
                    "Status A": "Aprovado" if it_a.get("recuperado_com_sucesso") else "Falha",
                    "Status B": "Aprovado" if it_b.get("recuperado_com_sucesso") else "Falha",
                })

            if tabela_comp:
                st.markdown("##### Tabela Comparativa de Recuperação por Pergunta")
                st.dataframe(tabela_comp, width='stretch', hide_index=True)

        with tab_t_raw:
            st.markdown("##### Dados Consolidados da Bateria de Avaliação")
            st.download_button(
                label="Baixar Relatório Completo (JSON)",
                data=json.dumps(rel_ativo, indent=2, ensure_ascii=False),
                file_name="relatorio_avaliacao_d02.json",
                mime="application/json",
            )
            st.json(rel_ativo)
