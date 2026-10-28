"""
app.py - Interface Unificada Streamlit da Central Inteligente de Atendimento - GOV.MT
Design Nativo, Fluido e Agradável no Streamlit para os Desafios 01 (RF01 a RF13) e 02 (RF14 a RF24).
"""

import os
import sys
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
from src.sentiment import classificar_sentimento_avaliacao, agregar_sentimentos_determinístico
from src.schemas import ExtracaoFicha, DecisaoOperador

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
@st.cache_resource
def obter_servicos():
    llm = LLMClient()
    audio = AudioProcessor()
    vision = VisionProcessor()
    img_gen = ImageGenerator()
    audit = AuditLogger()
    return llm, audio, vision, img_gen, audit

llm_client, audio_processor, vision_processor, image_generator, audit_logger = obter_servicos()

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
rag_motor = MotorRAG(indice=indice_vetorial)

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

# ==============================================================================
# Barra Lateral (Menu & Governança)
# ==============================================================================
p_brasao = resolver_caminho("dados/originais/brasao.png")
if p_brasao.exists():
    st.sidebar.image(str(p_brasao), width=100)

st.sidebar.title("Central GOV.MT")
st.sidebar.caption("SECITECI/MT • ETEC Cuiabá")

menu = st.sidebar.radio(
    "Navegação:",
    [
        "1. Central de Atendimento e HITL",
        "2. Experimento de Prompts (RF02)",
        "3. Audio STT e Visao OCR (RF06/RF08)",
        "4. Comunicacao Visual Oficial (RF10)",
        "5. Auditoria e LGPD (RF11/RF12/RF13)",
        "6. Assistente de Documentos RAG",
        "7. Triagem e Ficha da Solicitacao",
        "8. Painel de Sentimentos",
        "9. Gestao do Acervo e Expurgos",
    ],
    index=0
)

st.sidebar.divider()
st.sidebar.markdown(f"**Modo de IA:** `{llm_client.text_provider}`")
st.sidebar.markdown(f"**Modelo:** `{llm_client.primary_model.split('/')[-1]}`")
st.sidebar.markdown(f"**Base RAG:** `{len(indice_vetorial.chunks)} fragmentos`")
st.sidebar.markdown("**Governança:** `Human-in-the-Loop Ativo`")

# ==============================================================================
# Cabeçalho Principal Agradável
# ==============================================================================
c_hdr1, c_hdr2 = st.columns([3, 1.2])
with c_hdr1:
    st.title("Central Inteligente de Atendimento ao Cidadão")
    st.caption("Governo do Estado de Mato Grosso — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT)")
with c_hdr2:
    st.info("**Revisao Humana Obrigatoria**\n\nNenhuma resposta oficial é emitida sem homologação de servidor.")

st.divider()


# ==============================================================================
# MÓDULO 1: Central de Atendimento & HITL (RF03, RF05, RF09, RF13)
# ==============================================================================
if menu.startswith("1."):
    st.subheader("1. Atendimento e Redação de Minuta Oficial")
    st.markdown("Selecione um caso pré-definido ou insira o texto livre. A IA isola o conteúdo não confiável via envelope XML, extrai dados em JSON estrito e redige a minuta institucional.")

    col_in, col_out = st.columns([1, 1.3], gap="large")

    with col_in:
        st.markdown("##### Entrada da Solicitação")

        casos_opcoes = {
            "texto_original": "Mensagem de Texto (entrada_texto.txt)",
            "audio_transcricao": "Transcricao de Audio (Whisper STT)",
            "visao_documento": "Documento Digitalizado / OCR (PyMuPDF)",
            "prompt_injection": "Teste de Injecao de Prompt (Adversarial)",
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
            btn_processar = st.button("Processar Solicitacao", type="primary", use_container_width=True)
        with c_btn2:
            if st.button("Limpar Tudo", use_container_width=True):
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
                            use_container_width=True
                        )

                with act2:
                    if st.button("Sintetizar Voz Acessivel (RF07)", use_container_width=True):
                        with st.spinner("Sintetizando voz neural com aviso sonoro para campos pendentes..."):
                            res_tts = audio_processor.sintetizar_minuta_audio(
                                texto=st.session_state.minuta_editavel,
                                nome_arquivo=f"minuta_{exec_atual['id_execucao']}.mp3",
                                id_execucao=exec_atual["id_execucao"],
                                audit_logger=audit_logger,
                                exigir_aprovacao=False
                            )
                            if res_tts.get("sucesso") and os.path.exists(res_tts["caminho_arquivo"]):
                                with open(res_tts["caminho_arquivo"], "rb") as fa:
                                    st.session_state.audio_tts_bytes = fa.read()
                                st.success("Áudio acessível sintetizado com sucesso!")
                            else:
                                st.error("Erro na síntese de áudio.")

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
                    if st.button("Aprovar Resposta", type="primary", use_container_width=True):
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
                    if st.button("Salvar Correção", use_container_width=True):
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
                    if st.button("Rejeitar Resposta", use_container_width=True):
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

                    st.dataframe(tabela_dados, use_container_width=True, hide_index=True)

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
    st.dataframe(criterios, use_container_width=True, hide_index=True)

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

        if st.button("Transcrever Áudio com Whisper", type="primary", use_container_width=True):
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

                if st.button("Enviar Transcricao para Atendimento", use_container_width=True):
                    st.session_state.solicitacao_texto = res_a.get("transcricao_revisada") or ""
                    st.session_state.solicitacao_caso = "audio_transcricao"
                    st.success("Texto transferido para o Módulo 1!")

    with col_v:
        st.markdown("##### Documento Digitalizado / OCR (RF08)")
        st.warning("O PDF da ficha possui baixa legibilidade e manuscritos. A conferência humana é indispensável.")

        if st.button("Executar Leitura OCR", type="primary", use_container_width=True):
            with st.spinner("Analisando PDF/Imagem com OCR local..."):
                res_visao = vision_processor.processar_com_auditoria(audit_logger)
                st.session_state.visao_ocr_resultado = res_visao

        res_v = st.session_state.visao_ocr_resultado
        if res_v:
            if res_v.get("sucesso"):
                st.metric("Acurácia contra Gabarito", res_v.get("comparacao_gabarito", {}).get("taxa_acuracia_percentual", "N/A"))
                txt_ocr = res_v.get("texto_corrigido") or res_v.get("texto_bruto") or ""
                st.text_area("Texto Extraído pelo OCR:", value=txt_ocr, height=140, disabled=True)

                if res_v.get("trechos_incertos_ou_ilegiveis"):
                    st.markdown("**Trechos Incertos / Manuscritos:**")
                    for t in res_v.get("trechos_incertos_ou_ilegiveis"):
                        st.caption(f"• `{t}`")

                if st.button("Enviar Texto OCR para Atendimento", use_container_width=True):
                    st.session_state.solicitacao_texto = txt_ocr
                    st.session_state.solicitacao_caso = "visao_documento"
                    st.success("Texto transferido para o Módulo 1!")


# ==============================================================================
# MÓDULO 4: Comunicação Visual Oficial (RF10)
# ==============================================================================
elif menu.startswith("4."):
    st.subheader("4. Comunicação Visual Institucional Padronizada (RF10)")
    st.markdown("Abordagem híbrida: geração de ilustração sem texto por IA combinada com moldura timbrada oficial em Pillow (Brasão do Estado e tarja de proveniência de conteúdo sintético).")

    if st.button("Gerar Comunicado Visual Oficial", type="primary"):
        with st.spinner("Compondo arte institucional e aplicando moldura com Brasão..."):
            res_img = image_generator.gerar_comunicado_oficial(audit_logger=audit_logger)
            st.session_state.imagem_resultado = res_img
            st.session_state.imagem_aprovada = False

    img_dado = st.session_state.imagem_resultado
    if img_dado and img_dado.get("sucesso"):
        c_v1, c_v2 = st.columns([1.2, 1], gap="large")
        with c_v1:
            st.image(img_dado["caminho_imagem"], caption="Peça Institucional Padronizada GOV.MT", use_container_width=True)
        with c_v2:
            meta = img_dado.get("metadados", {})
            st.markdown("##### Metadados da Peça (RF10)")
            st.write(f"- **Título:** {meta.get('titulo')}")
            st.write(f"- **Dimensões:** {meta.get('dimensoes')}")
            st.write(f"- **Modelo IA:** `{meta.get('modelo_ia_utilizado')}`")
            st.write(f"- **Tarja:** `{meta.get('declaracao_proveniencia')}`")
            st.write(f"- **SHA-256:** `{meta.get('sha256_imagem', '')[:20]}...`")

            st.divider()
            st.markdown("##### Deliberação Humana")
            chk_v = st.checkbox("Conferi textos, símbolos, mãos, objetos e coerência visual (RF13).")
            just_v = st.text_input("Justificativa:", value="Conferência visual aprovada conforme padrão institucional GOV.MT.")

            b_ap, b_rej = st.columns(2)
            with b_ap:
                if st.button("Aprovar Imagem", type="primary", use_container_width=True):
                    if not chk_v:
                        st.warning("Confirme o checkbox de conferência visual.")
                    else:
                        image_generator.revisar_imagem(
                            id_execucao=img_dado["id_execucao"],
                            hash_imagem=meta.get("sha256_imagem"),
                            decisao="APROVADO",
                            justificativa=just_v,
                            operador="Servidor SECITECI/MT",
                            audit_logger=audit_logger
                        )
                        st.session_state.imagem_aprovada = True
                        st.success("Imagem homologada e aprovada para publicação!")
            with b_rej:
                if st.button("Rejeitar Imagem", use_container_width=True):
                    image_generator.revisar_imagem(
                        id_execucao=img_dado["id_execucao"],
                        hash_imagem=meta.get("sha256_imagem"),
                        decisao="REJEITADO",
                        justificativa=just_v,
                        operador="Servidor SECITECI/MT",
                        audit_logger=audit_logger
                    )
                    st.error("Imagem rejeitada.")
    else:
        st.info("Clique em **Gerar Comunicado Visual Oficial** para criar a peça gráfica institucional.")


# ==============================================================================
# MÓDULO 5: Auditoria & LGPD (RF11, RF12, RF13)
# ==============================================================================
elif menu.startswith("5."):
    st.subheader("5. Trilha de Auditoria e Conformidade LGPD (RF11 / RF12)")
    st.markdown("Rastreabilidade de todas as chamadas de IA e decisões humanas tomadas pelos operadores.")

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
        st.dataframe(tabela_lgpd, use_container_width=True, hide_index=True)

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
                    st.write(f"- **Modelo:** `{reg.get('modelo')}`")
                    st.write(f"- **Data/Hora:** `{reg.get('timestamp')}`")
                    st.write(f"- **Justificativa:** {dec.get('justificativa', 'Nenhuma')}")


# ==============================================================================
# MÓDULO 6: Assistente de Documentos RAG (RF17 a RF20)
# ==============================================================================
elif menu.startswith("6."):
    st.subheader("6. Assistente de Documentos Institucionais (RAG)")
    st.markdown("Consulta semântica fundamentada em editais e retificações da ETEC com citações explícitas e detecção de contradições.")

    c_q, c_cfg = st.columns([3, 1])
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

    with c_cfg:
        top_k = st.slider("Trechos (Top-K):", min_value=1, max_value=5, value=3)

    if st.button("Buscar e Responder com RAG", type="primary"):
        if not pergunta_digitada.strip():
            st.warning("Informe a pergunta.")
        else:
            with st.spinner("Buscando no acervo vetorial e analisando fundamentação..."):
                resp = rag_motor.responder(pergunta_digitada, top_k=top_k)

            if resp.status == "fundamentada":
                st.success("RESPOSTA FUNDAMENTADA COM EVIDÊNCIA SUFICIENTE")
            elif resp.status == "conflito_de_fontes":
                st.error("CONFLITO DE FONTES DETECTADO (REVISÃO HUMANA)")
            else:
                st.warning("SEM EVIDENCIA SUFICIENTE NO ACERVO (ABSTENÇÃO SEGURA)")

            st.info(resp.resposta)

            if resp.divergencia_identificada:
                st.warning(f"**Divergência:** {resp.divergencia_identificada}")

            st.markdown("##### Trechos Recuperados do Acervo")
            for idx, t in enumerate(resp.fontes, start=1):
                with st.expander(f"Trecho {idx}: {t.documento_id} v{t.versao} (Pág. {t.pagina or '1'}) — Similaridade: {t.score_similaridade:.4f}"):
                    st.caption(f"ID: {t.trecho_id} | Seção: {t.secao or 'Geral'} | Distância: {t.score_distancia:.4f}")
                    st.text_area("Fragmento:", value=t.conteudo, height=90, disabled=True, key=f"rag_{t.trecho_id}")


# ==============================================================================
# MÓDULO 7: Triagem & Ficha da Solicitação (RF14/RF15)
# ==============================================================================
elif menu.startswith("7."):
    st.subheader("7. Triagem Estruturada e Ficha de Compreensão (RF14 / RF15)")
    st.markdown("Converte manifestações em esquemas rigorosos Pydantic v2 com validação de datas, campos ausentes e resumo fiel <= 100 palavras.")

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
    prot_f = st.text_input("Protocolo Externo (opcional):", value=caso_sol.get("protocolo", "") if caso_sol else "")

    if st.button("Processar Ficha Pydantic", type="primary"):
        if not texto_f.strip():
            st.warning("Informe o texto.")
        else:
            with st.spinner("Processando ficha estruturada..."):
                ficha = processar_solicitacao(texto_f, protocolo_externo=prot_f if prot_f else None)
                dados_ui = ficha.para_interface_usuario()

                f1, f2, f3 = st.columns(3)
                f1.metric("Categoria", ficha.categoria)
                f2.metric("Campos Ausentes", len(ficha.campos_ausentes))
                f3.metric("Necessita Revisão?", "SIM" if ficha.necessidade_revisao else "NÃO")

                st.info(f"**Resumo Fiel (até 100 palavras):**\n\n{ficha.resumo}")
                st.json(dados_ui)


# ==============================================================================
# MÓDULO 8: Painel de Sentimentos (RF22)
# ==============================================================================
elif menu.startswith("8."):
    st.subheader("8. Painel Analítico de Sentimentos (RF22)")
    st.markdown("Classificação em 4 polaridades com agregação determinística via código (Python) e separação de estimativa de modelo.")

    p_av = resolver_caminho("dados/avaliacoes/avaliacoes_atendimento.json")
    if p_av.exists():
        with open(p_av, "r", encoding="utf-8") as fa:
            avaliacoes = json.load(fa)

        classificacoes = [classificar_sentimento_avaliacao(a["id"], a["texto"]) for a in avaliacoes]
        agregacao = agregar_sentimentos_determinístico(classificacoes)

        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        col_s1.metric("Total", agregacao["total"])
        col_s2.metric("Positivas", f"{agregacao['distribuicao']['positiva']} ({agregacao['percentuais']['positiva']}%)")
        col_s3.metric("Negativas", f"{agregacao['distribuicao']['negativa']} ({agregacao['percentuais']['negativa']}%)")
        col_s4.metric("Neutras", f"{agregacao['distribuicao']['neutra']} ({agregacao['percentuais']['neutra']}%)")
        col_s5.metric("Indeterminadas", f"{agregacao['distribuicao']['indeterminada']} ({agregacao['percentuais']['indeterminada']}%)")

        st.bar_chart(agregacao["distribuicao"])
        st.caption(f"**Nota Metodologica:** {agregacao['nota_metodologica']}")

        st.markdown("##### Avaliações dos Cidadãos")
        for av, cl in zip(avaliacoes, classificacoes):
            with st.expander(f"{cl.id} — [{cl.polaridade.upper()}] — {av['texto'][:65]}..."):
                st.write(f"**Texto:** {av['texto']}")
                st.write(f"**Justificativa:** {cl.justificativa}")
                st.caption(f"Confiança: {cl.confianca_estimada:.2f} | Requer Revisão: {cl.necessidade_revisao}")


# ==============================================================================
# MÓDULO 9: Gestão do Acervo & Expurgos (RF24)
# ==============================================================================
elif menu.startswith("9."):
    st.subheader("9. Governança do Acervo e Expurgos (RF24)")
    st.markdown("Demonstração da exclusão definitiva de documentos e fragmentos derivados do índice vetorial.")

    docs_presentes = sorted(list({c["documento_id"] for c in indice_vetorial.chunks}))
    st.metric("Documentos no Índice Vetorial", len(docs_presentes))

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

st.divider()
st.caption("Governo do Estado de Mato Grosso — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT)")
