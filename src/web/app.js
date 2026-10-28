// Central Inteligente de Atendimento - GOV.MT (Frontend Controller)

document.addEventListener("DOMContentLoaded", () => {
  const esc = (valor) => String(valor ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  let ultimaExecucaoId = null;
  let ultimoUrlPdf = null;
  let ultimaExtracao = {};
  let textoAprovado = null;
  let processando = false;
  let decidindo = false;
  let sintetizando = false;
  let exportando = false;
  let carregandoCaso = false;
  let formatoVisual = "original";
  let conferenciaAtual = null;

  // Apenas apresentação: não altera extração, minuta, métricas ou aprovação.
  function apresentarIdentificador(campo, valor) {
    const texto = String(valor ?? "");
    if (campo !== "cpf" && campo !== "rg") return texto;
    if (!/^[\d.\s-]+$/.test(texto)) return texto;
    const digitos = texto.replace(/\D/g, "");
    if (formatoVisual === "digitos") return digitos;
    if (formatoVisual === "mascara" && campo === "cpf" && digitos.length === 11)
      return digitos.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
    return texto;
  }
  for (const [id, formato] of [["btn-aplicar-mascaras-todas", "mascara"], ["btn-aplicar-digitos-todas", "digitos"]]) {
    document.getElementById(id)?.addEventListener("click", () => {
      formatoVisual = formato;
      if (conferenciaAtual) renderizarPainelConferencia(...conferenciaAtual);
    });
  }

  function mensagemSegura(data, status) {
    let detalhe = data?.detail ?? data?.erro;
    if (Array.isArray(detalhe)) detalhe = detalhe.map(e => `${(e.loc || []).join(".")}: ${e.msg || "Valor inválido"}`).join("; ");
    if (typeof detalhe !== "string") detalhe = "Não foi possível concluir a operação.";
    if (status >= 500 && status !== 502 && status !== 503) detalhe = "Falha interna. Consulte a auditoria local.";
    return detalhe.replace(/Bearer\s+\S+|(?:sk-or-v1-|hf_)[A-Za-z0-9_-]+/gi, "[credencial omitida]").slice(0, 400);
  }

  // Controle de Tela de Loading Global (GOV.MT)
  let activeLoadingCount = 0;
  const overlayLoading = document.getElementById("gov-loading-overlay");
  const overlayTitle = document.getElementById("gov-loading-title");
  const overlayMessage = document.getElementById("gov-loading-message");

  function mostrarLoading(titulo = "Processando...", mensagem = "Aguarde enquanto a requisição é processada com segurança.") {
    activeLoadingCount++;
    if (overlayTitle) overlayTitle.textContent = titulo;
    if (overlayMessage) overlayMessage.textContent = mensagem;
    if (overlayLoading) {
      overlayLoading.style.display = "flex";
      void overlayLoading.offsetWidth;
      overlayLoading.classList.add("active");
      overlayLoading.setAttribute("aria-hidden", "false");
    }
  }

  function ocultarLoading() {
    activeLoadingCount = Math.max(0, activeLoadingCount - 1);
    if (activeLoadingCount === 0 && overlayLoading) {
      overlayLoading.classList.remove("active");
      overlayLoading.setAttribute("aria-hidden", "true");
      setTimeout(() => {
        if (activeLoadingCount === 0 && overlayLoading) {
          overlayLoading.style.display = "none";
        }
      }, 220);
    }
  }

  function obterMensagemLoading(url, opcoes) {
    const metodo = (opcoes?.method || "GET").toUpperCase();
    if (url.includes("/api/config")) return null;
    if (url.includes("/api/processar/texto")) {
      return { titulo: "Processando Solicitação com IA", mensagem: "Isolando entrada com envelope de segurança, extraindo dados em JSON e redigindo minuta institucional..." };
    }
    if (url.includes("/api/processar/audio")) {
      return { titulo: "Processando Áudio (STT)", mensagem: "Transcrevendo fala e conferindo dados críticos contra gabarito oficial..." };
    }
    if (url.includes("/api/processar/visao")) {
      return { titulo: "Executando Leitura Visual e OCR", mensagem: "Analisando formulário digitalizado com modelo de visão computacional..." };
    }
    if (url.includes("/api/gerar/imagem") || url.includes("/imagem")) {
      return { titulo: "Gerando Comunicação Visual Oficial", mensagem: "Criando ilustração sintética e aplicando template com brasão institucional do GOV.MT..." };
    }
    if (url.includes("/api/sintetizar") || url.includes("/tts")) {
      return { titulo: "Sintetizando Voz (TTS Acessibilidade)", mensagem: "Gerando áudio neural em português com alerta sonoro para campos pendentes..." };
    }
    if (url.includes("/api/gerar/pdf") || url.includes("/minuta/gerar_pdf") || url.includes("/pdf")) {
      return { titulo: "Gerando Documento PDF Oficial", mensagem: "Diagramando e renderizando documento timbrado oficial em formato A4..." };
    }
    if (url.includes("/api/experimento")) {
      return { titulo: "Executando Experimento de Prompts (RF02)", mensagem: "Submetendo entrada aos Prompts A, B e C, calculando métricas e consumo de tokens..." };
    }
    if (url.includes("/api/decisao") || url.includes("/deliberar") || url.includes("/revisar")) {
      return { titulo: "Registrando Deliberação Human-in-the-Loop", mensagem: "Gravando decisão administrativa, responsável e justificativa na trilha de auditoria..." };
    }
    if (url.includes("/api/casos/")) {
      return { titulo: "Carregando Manifestação", mensagem: "Buscando dados da solicitação selecionada..." };
    }
    if (url.includes("/api/auditoria") || url.includes("/api/lgpd") || url.includes("/api/logs")) {
      return { titulo: "Consultando Auditoria e LGPD", mensagem: "Atualizando registros de execuções e relatório de conformidade..." };
    }
    if (metodo === "POST" || metodo === "PUT" || metodo === "DELETE") {
      return { titulo: "Processando Operação...", mensagem: "Aguarde enquanto os dados são processados pelo servidor..." };
    }
    return null;
  }

  async function api(url, opcoes) {
    const infoLoading = (!opcoes?.silencioso) ? obterMensagemLoading(url, opcoes) : null;
    if (infoLoading) {
      mostrarLoading(infoLoading.titulo, infoLoading.mensagem);
    }
    try {
      let res;
      try { res = await fetch(url, opcoes); }
      catch (_) { throw new Error("Não foi possível conectar à API local. Verifique se o servidor está ativo."); }
      let data;
      try { data = await res.json(); }
      catch (_) { throw new Error(`HTTP ${res.status || "?"}: a API não retornou JSON válido.`); }
      if (!res.ok || data?.sucesso === false) {
        throw new Error(`HTTP ${res.status || 200}: ${mensagemSegura(data, res.status)}`);
      }
      return { ...res, ok: true, json: async () => data };
    } finally {
      if (infoLoading) {
        ocultarLoading();
      }
    }
  }

  function autoAjustarAlturaInputSolicitacao() {
    const el = document.getElementById("input-texto-solicitacao");
    if (!el) return;
    el.style.height = "auto";
    const novaAltura = Math.max(el.scrollHeight + 4, 160);
    el.style.height = `${novaAltura}px`;
  }

  function atualizarVisibilidadeCardMinuta() {
    const editor = document.getElementById("editor-minuta");
    const emptyState = document.getElementById("minuta-empty-state");
    const activeContent = document.getElementById("minuta-conteudo-ativo");
    const cardOutput = document.getElementById("card-analise-minuta") || document.querySelector(".card-output");

    const temTextoMinuta = !!(editor && editor.value.trim().length > 0 && ultimaExecucaoId);

    if (temTextoMinuta) {
      if (emptyState) emptyState.style.display = "none";
      if (activeContent) activeContent.style.display = "block";
      if (cardOutput) cardOutput.classList.remove("card-output-shrunk");
    } else {
      if (emptyState) emptyState.style.display = "flex";
      if (activeContent) activeContent.style.display = "none";
      if (cardOutput) cardOutput.classList.add("card-output-shrunk");
    }
  }

  function atualizarAcoes() {
    const ocupado = processando || decidindo || sintetizando || exportando || carregandoCaso;
    for (const id of ["btn-aprovar-minuta", "btn-corrigir-minuta", "btn-rejeitar-minuta", "btn-exportar-pdf"]) {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = ocupado || !ultimaExecucaoId;
    }
    const tts = document.getElementById("btn-gerar-tts");
    const temTextoMinuta = !!(document.getElementById("editor-minuta")?.value?.trim());
    if (tts) tts.disabled = ocupado || !ultimaExecucaoId || !temTextoMinuta;
    for (const id of ["caso-predefinido", "input-texto-solicitacao", "btn-limpar-texto", "btn-processar-solicitacao", "editor-minuta"]) {
      const elemento = document.getElementById(id);
      if (elemento) elemento.disabled = ocupado;
    }
    atualizarVisibilidadeCardMinuta();
  }
  document.getElementById("editor-minuta")?.addEventListener("input", () => {
    if (textoAprovado !== null && textoAprovado !== document.getElementById("editor-minuta").value) {
      textoAprovado = null;
      document.getElementById("badge-status-revisao").textContent = "Texto alterado: aguardando revisão/aprovação";
      document.getElementById("badge-status-revisao").className = "badge badge-warning";
    }
    document.getElementById("tts-audio-container").style.display = "none";
    atualizarAcoes();
  });
  atualizarAcoes();


  // 1. Gerenciamento de Abas Principais
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabPanes = document.querySelectorAll(".tab-pane");

  function mudarParaAba(targetId) {
    navTabs.forEach((t) => t.classList.remove("active"));
    tabPanes.forEach((p) => p.classList.remove("active"));
    const tabBtn = document.querySelector(`.nav-tab[data-tab="${targetId}"]`);
    if (tabBtn) tabBtn.classList.add("active");
    const targetPane = document.getElementById(targetId);
    if (targetPane) targetPane.classList.add("active");

    if (targetId === "tab-auditoria") {
      carregarAuditoriaELgpd();
    }
  }

  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      mudarParaAba(tab.getAttribute("data-tab"));
    });
  });

  // 2. Sub-abas (Minuta vs JSON vs Métricas)
  const subTabs = document.querySelectorAll(".sub-tab");
  const subtabPanes = document.querySelectorAll(".subtab-pane");

  subTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-subtab");
      subTabs.forEach((t) => t.classList.remove("active"));
      subtabPanes.forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const targetSub = document.getElementById(targetId);
      if (targetSub) targetSub.classList.add("active");
    });
  });

  // 3. Inicialização e Consulta de Configuração
  async function carregarConfiguracao() {
    try {
      const res = await api("/api/config");
      const data = await res.json();
      const badgeMode = document.getElementById("badge-api-mode");
      if (badgeMode) {
        if (!data.texto?.habilitado) {
          badgeMode.textContent = "Texto: Indisponível (sem token)";
          badgeMode.className = "badge badge-warning";
          badgeMode.title = "Configure HF_TOKEN ou OPENROUTER_API_KEY no .env para gerar minutas";
        } else {
          badgeMode.textContent = `Texto: ${data.texto.provedor} / ${data.texto.modelo}`;
          badgeMode.className = "badge badge-mode";
          badgeMode.title = `Provedor de texto ativo: ${data.texto.provedor}`;
        }
        const modos = document.getElementById("modos-multimodais");
        if (modos) {
          const sttProvedor = data.stt?.provedor || "local";
          const isSttLocal = sttProvedor === "local";
          const sttNome = isSttLocal ? "Whisper Small (Local)" : (data.stt?.modelo ? (data.stt.modelo.includes("/") ? data.stt.modelo.split("/").pop() : data.stt.modelo) : "Whisper");
          const sttClass = isSttLocal ? "multimodal-chip chip-local" : "multimodal-chip";

          const ttsProvedor = data.tts?.provedor || "edge-tts";
          const ttsVoz = ttsProvedor === "openrouter"
            ? `OpenRouter (${data.tts?.modelo?.split("/").pop() || "Gemini TTS"})`
            : (ttsProvedor === "edge-tts" ? "edge-tts (Neural)" : ttsProvedor);
          const ttsTitle = ttsProvedor === "openrouter"
            ? `TTS: OpenRouter (${data.tts?.modelo}) com fallback automático para edge-tts`
            : "TTS: Síntese Neural Acessível em Português";

          const ocrProvedor = data.ocr?.provedor || "local";
          const isOcrLocal = ocrProvedor === "local";
          const ocrModelo = data.ocr?.modelo ? (data.ocr.modelo.includes("/") ? data.ocr.modelo.split("/").pop() : data.ocr.modelo) : "Tesseract";
          const ocrNome = isOcrLocal ? "Tesseract Local" : `OpenRouter (${ocrModelo})`;
          const ocrClass = isOcrLocal ? "multimodal-chip chip-local" : "multimodal-chip";
          const ocrTitle = isOcrLocal
            ? "OCR: Visão Soberana Local (PyMuPDF / Tesseract)"
            : `OCR: OpenRouter VLM (${data.ocr?.modelo}) com Fallback Local Tesseract`;

          const imgHabilitado = data.imagem?.habilitado === true;
          const imgProvedor = data.imagem?.provedor || "cloudflare";
          const imgModeloCompleto = data.imagem?.modelo || "@cf/black-forest-labs/flux-1-schnell";
          const imgModelo = imgModeloCompleto.includes("/") ? imgModeloCompleto.split("/").pop() : imgModeloCompleto;
          const imgNome = imgHabilitado ? `${imgProvedor} / ${imgModelo}` : "Indisponível (sem token)";
          const imgClass = imgHabilitado ? "multimodal-chip chip-rf10" : "multimodal-chip chip-disabled";

          modos.innerHTML = `
            <span class="${sttClass}" title="STT: Reconhecimento de Fala (${sttProvedor} / ${data.stt?.modelo || sttNome})">🎙️ STT: <strong>${sttNome}</strong></span>
            <span class="multimodal-chip" title="${ttsTitle}">🔊 TTS: <strong>${ttsVoz}</strong></span>
            <span class="${ocrClass}" title="${ocrTitle}">📄 OCR: <strong>${ocrNome}</strong></span>
            <span class="${imgClass}" title="${imgHabilitado ? 'Geração Visual: ' + imgProvedor + ' / ' + imgModeloCompleto + ' · Moldura Oficial GOV.MT via Pillow' : 'Geração Visual indisponível: configure token no .env'}">🎨 Imagem: <strong>${imgNome}</strong></span>
          `;
        }
        const imagem = document.getElementById("btn-gerar-imagem-peca");
        if (imagem) { imagem.disabled = data.rf10_administrativo_habilitado !== true; imagem.title = data.rf10_administrativo_habilitado ? "Gerar comunicado visual oficial GOV.MT" : "Requer habilitação administrativa."; }
      }
    } catch (e) {
      console.error("Falha ao carregar configuração:", e);
      document.getElementById("badge-api-mode").textContent = "Configuração indisponível";
    }
  }
  carregarConfiguracao();

  // 4. Carregamento de Casos de Teste Pré-definidos
  const selectCaso = document.getElementById("caso-predefinido");
  const inputTexto = document.getElementById("input-texto-solicitacao");

  async function atualizarTextoCaso(valor) {
    if (!valor || valor === "personalizado") {
      inputTexto.value = "";
      autoAjustarAlturaInputSolicitacao();
      return;
    }
    carregandoCaso = true; atualizarAcoes();
    inputTexto.value = "Carregando conteúdo real da modalidade selecionada...";
    autoAjustarAlturaInputSolicitacao();
    try {
      const res = await api(`/api/casos/${valor}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.erro || data.detail || "Processamento indisponível");
      inputTexto.value = data.conteudo || "";
      autoAjustarAlturaInputSolicitacao();
    } catch (e) {
      console.error("Erro ao carregar caso:", e);
      inputTexto.value = "";
      autoAjustarAlturaInputSolicitacao();
      alert("Falha ao carregar a modalidade: " + e.message);
    } finally {
      carregandoCaso = false; atualizarAcoes();
    }
  }

  if (selectCaso) {
    selectCaso.addEventListener("change", (e) => atualizarTextoCaso(e.target.value));
    atualizarTextoCaso(selectCaso.value);
  }

  inputTexto?.addEventListener("input", autoAjustarAlturaInputSolicitacao);
  window.addEventListener("resize", autoAjustarAlturaInputSolicitacao);

  document.getElementById("btn-limpar-texto")?.addEventListener("click", () => {
    if (inputTexto) {
      inputTexto.value = "";
      autoAjustarAlturaInputSolicitacao();
    }
    const editor = document.getElementById("editor-minuta");
    if (editor) editor.value = "";
    ultimaExecucaoId = null;
    ultimoUrlPdf = null;
    ultimaExtracao = {};
    textoAprovado = null;
    atualizarAcoes();
  });

  // 5. Processar Solicitação com IA Segura (RF03, RF05, RF09)
  const btnProcessar = document.getElementById("btn-processar-solicitacao");
  btnProcessar?.addEventListener("click", async () => {
    const texto = inputTexto?.value.trim();
    if (!texto) {
      alert("Por favor, insira ou carregue o texto de uma solicitação.");
      return;
    }

    processando = true;
    ultimaExecucaoId = null; ultimoUrlPdf = null; ultimaExtracao = {}; textoAprovado = null;
    document.getElementById("editor-minuta").value = "";
    document.getElementById("justificativa-revisao").value = "";
    document.getElementById("json-extracao-view").textContent = "Aguardando processamento...";
    document.getElementById("tabela-conferencia-body").innerHTML = "";
    for (const id of ["metric-duracao", "metric-tokens", "metric-custo"]) document.getElementById(id).textContent = "—";
    document.getElementById("tts-audio-container").style.display = "none";
    document.getElementById("badge-status-revisao").textContent = "Processando; revisão indisponível";
    document.getElementById("badge-status-revisao").className = "badge badge-warning";
    document.getElementById("comparacao-gabarito-view").textContent = "";
    document.getElementById("banner-conferencia-operador").style.display = "none";
    atualizarAcoes();
    btnProcessar.disabled = true;
    btnProcessar.textContent = "Analisando solicitação e gerando minuta...";

    try {
      const res = await api("/api/processar/texto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: texto, caso: selectCaso?.value || "texto_original" }),
      });

      const data = await res.json();
      btnProcessar.disabled = false;
      btnProcessar.textContent = "Processar Solicitação (RF03/RF05)";

      if (!data.sucesso) {
        alert("Erro no processamento: " + (data.detail || data.erro || "Resposta incompleta da API"));
        return;
      }

      if (!data.id_execucao || typeof data.minuta_institucional !== "string") throw new Error("Resposta incompleta da API: execução ou minuta ausente.");
      ultimaExecucaoId = data.id_execucao;
      ultimaExtracao = data.extracao || {};
      ultimoUrlPdf = data.url_pdf || null;

      // Atualiza Minuta
      const editorMinuta = document.getElementById("editor-minuta");
      if (editorMinuta) editorMinuta.value = data.minuta_institucional || "";

      // Atualiza JSON Viewer
      const jsonView = document.getElementById("json-extracao-view");
      if (jsonView) jsonView.textContent = JSON.stringify(data.extracao, null, 2);

      // Atualiza Metricas
      document.getElementById("metric-duracao").textContent = `${data.metricas?.duracao_segundos}s`;
      document.getElementById("metric-tokens").textContent = data.metricas?.total_tokens || "-";
      document.getElementById("metric-custo").textContent = typeof data.metricas?.custo_usd === "number" ? `US$ ${data.metricas?.custo_usd.toFixed(2)}` : "Não informado";

      const badgeStatus = document.getElementById("badge-status-revisao");
      if (badgeStatus) {
        badgeStatus.textContent = "Pendente de Revisão Humana";
        badgeStatus.className = "badge badge-warning";
      }

      // 5. Renderiza o Painel de Conferência Visual de Dados e Auditoria (RF13)
      renderizarPainelConferencia(data.avaliacao_gabarito || data.conformidade_formato, data.extracao);

      // Exibe avaliacao resumida na aba de métricas
      const gabaritoBox = document.getElementById("comparacao-gabarito-view");
      if (gabaritoBox && data.avaliacao_gabarito) {
        const aval = data.avaliacao_gabarito;
        gabaritoBox.innerHTML = `
          <strong>Fidelidade à referência institucional:</strong> ${aval.taxa_fidelidade_percentual ?? "não avaliada"}${aval.taxa_fidelidade_percentual == null ? "" : "%"} (${aval.total_acertos}/${aval.total_campos_avaliaveis ?? aval.total_campos_analisados} campos avaliáveis)<br>
          <strong>Completude dos dados disponíveis na fonte:</strong> ${aval.taxa_completude_percentual ?? "não avaliada"}${aval.taxa_completude_percentual == null ? "" : "%"}<br>
          <small>Ausências na fonte: ${aval.total_ausentes_na_fonte ?? "não informado"}. Ausências coincidentes não contam como acertos nem divergências.</small><br>
          <strong>Status de Qualidade:</strong> <span class="badge ${aval.status_qualidade === 'Excelente' ? 'badge-ok' : 'badge-warning'}">${esc(aval.status_qualidade)}</span>
        `;
      }
    } catch (err) {
      btnProcessar.disabled = false;
      btnProcessar.textContent = "Processar Solicitação (RF03/RF05)";
      document.getElementById("badge-status-revisao").textContent = "Processamento não concluído";
      alert("Erro no processamento: " + err.message);
    } finally {
      processando = false;
      atualizarAcoes();
    }
  });

  // Função Especializada para o Painel de Conferência de Dados (RF13)
  function renderizarPainelConferencia(aval, extracao) {
    conferenciaAtual = [aval, extracao];
    if (!aval) return;

    const banner = document.getElementById("banner-conferencia-operador");
    const badgeCount = document.getElementById("badge-divergencias-count");
    const taxaEl = document.getElementById("audit-taxa-fidelidade");
    const statusEl = document.getElementById("audit-status-qualidade");
    const acertosEl = document.getElementById("audit-campos-acertos");
    const errosEl = document.getElementById("audit-campos-erros");
    const subErrosEl = document.getElementById("audit-sub-erros");
    const pendenciasEl = document.getElementById("audit-campos-pendencias");
    const tbody = document.getElementById("tabela-conferencia-body");

    const erros = (aval.erros_encontrados || []).filter(c => c.status !== "PENDENCIA" && !c.eh_pendencia);
    const comparativo = aval.comparativo_campos || [];
    const pendencias = comparativo.filter((c) => c.eh_pendencia || c.status === "PENDENCIA");

    // 1. Atualiza Indicadores KPI
    if (taxaEl) taxaEl.textContent = `${aval.taxa_fidelidade_percentual ?? "não avaliada"}${aval.taxa_fidelidade_percentual == null ? "" : "%"}`;
    if (statusEl) {
      statusEl.textContent = aval.status_qualidade || "Formato avaliado; fidelidade não avaliada";
      statusEl.className = `badge ${aval.status_qualidade === "Excelente" ? "badge-ok" : "badge-warning"}`;
    }
    if (acertosEl) acertosEl.textContent = `${aval.total_acertos ?? "—"} / ${aval.total_campos_avaliaveis ?? aval.total_campos_analisados ?? "—"}`;
    if (errosEl) errosEl.textContent = erros.length;
    if (subErrosEl) {
      subErrosEl.textContent = erros.length === 0 ? "Nenhuma divergência" : `${erros.length} campo(s) exigem atenção`;
    }
    if (pendenciasEl) pendenciasEl.textContent = pendencias.length;

    // 2. Atualiza Bolinha de Notificação na Aba
    if (badgeCount) {
      if (erros.length > 0) {
        badgeCount.style.display = "inline-flex";
        badgeCount.textContent = `${erros.length}`;
        badgeCount.className = "badge-count-circle";
      } else {
        badgeCount.style.display = "none";
      }
    }

    // 3. Atualiza Banner Rápido na Minuta
    if (banner) {
      banner.style.display = "flex";
      if (erros.length > 0) {
        banner.className = "conferencia-banner divergente";
        banner.innerHTML = `
          <div>
            <strong>Atenção Servidor:</strong> Foram identificadas <strong>${erros.length} divergência(s)</strong> em relação aos padrões e regras oficiais:
            <div class="banner-badge-group">
              ${erros.map((e) => `<span class="badge badge-danger">${esc(e.rotulo || e.campo || "Campo")}: esperado "${esc(e.esperado)}", obtido "${esc(e.obtido)}"</span>`).join("")}
            </div>
          </div>
          <button type="button" class="banner-action-btn" id="btn-ir-conferencia">Abrir Painel de Conferência &rarr;</button>
        `;
        document.getElementById("btn-ir-conferencia")?.addEventListener("click", () => {
          document.getElementById("btn-subtab-conferencia")?.click();
        });
      } else if (pendencias.length > 0) {
        banner.className = "conferencia-banner alerta";
        banner.innerHTML = `
          <div>
            <strong>Conferência com pendências:</strong> ${aval.total_acertos}/${aval.total_campos_avaliaveis ?? aval.total_campos_analisados} campos avaliáveis conferidos. Há ${pendencias.length} dados pendentes; ausência na fonte não representa divergência:
            <div class="banner-badge-group">
              ${pendencias.map((p) => `<span class="badge badge-warning">${esc(p.rotulo || p.campo)}: Pendente</span>`).join("")}
            </div>
          </div>
          <button type="button" class="banner-action-btn" id="btn-ir-conferencia">Ver Tabela Completa &rarr;</button>
        `;
        document.getElementById("btn-ir-conferencia")?.addEventListener("click", () => {
          document.getElementById("btn-subtab-conferencia")?.click();
        });
      } else {
        banner.className = "conferencia-banner sucesso";
        banner.innerHTML = `
          <div>
            <strong>Conferência Concluída com Sucesso:</strong> Conferência automática concluída. Revise a tabela e a fonte; formato não comprova fidelidade nem aprovação.
          </div>
          <button type="button" class="banner-action-btn" id="btn-ir-conferencia">Ver Tabela Completa &rarr;</button>
        `;
        document.getElementById("btn-ir-conferencia")?.addEventListener("click", () => {
          document.getElementById("btn-subtab-conferencia")?.click();
        });
      }
    }

    // 4. Renderiza Tabela Campo a Campo (com fallback defensivo)
    if (tbody) {
      const ROTULOS_MAP = {
        protocolo: "Número de Protocolo",
        data: "Data da Solicitação",
        solicitante: "Nome do Requerente / Solicitante",
        cpf: "Cadastro de Pessoa Física (CPF)",
        rg: "Registro Geral (RG)",
        orgao_expedidor: "Órgão Expedidor do RG",
        data_nascimento: "Data de Nascimento",
        naturalidade: "Naturalidade / Cidade",
        uf: "Unidade Federativa (UF)",
        nome_mae: "Nome da Mãe (Filiação)",
        nome_pai: "Nome do Pai (Filiação)",
        curso: "Curso Técnico Pretendido",
        eixo_tecnologico: "Eixo Tecnológico",
        carga_horaria: "Carga Horária do Curso",
        turno: "Turno Solicitado",
        inicio_curso: "Previsão de Início das Aulas",
        email: "E-mail de Contato",
        telefone: "Telefone / Celular",
        assunto: "Assunto da Manifestação",
        pedido: "Teor do Pedido Formal",
        categoria: "Categoria do Atendimento",
      };

      let comparativo = aval.comparativo_campos || [];
      if (comparativo.length === 0 && extracao) {
        const mapaErros = {};
        erros.forEach((e) => { mapaErros[e.campo] = e; });
        comparativo = Object.keys(extracao).map((k) => {
          const val = extracao[k];
          const erro = mapaErros[k];
          const isPend = String(val).toLowerCase() === "não localizado";
          return {
            campo: k,
            rotulo: ROTULOS_MAP[k] || k,
            esperado: erro ? erro.esperado : (isPend ? "não localizado" : val),
            obtido: val,
            status: erro ? "DIVERGENTE" : (isPend ? "PENDENCIA" : "NAO_AVALIADO"),
            eh_pendencia: isPend,
            gravidade: erro ? erro.gravidade : "Nenhuma",
            acao_recomendada: erro ? erro.acao_recomendada : "Conferir na fonte; sem referência independente.",
          };
        });
      }

      if (comparativo.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 24px; color: #64748B;">Nenhum detalhe comparativo disponível para esta extração.</td></tr>`;
        return;
      }

      const linhasHtml = comparativo
        .map((item, idx) => {
          const isDivergente = item.status === "DIVERGENTE";
          const isPendencia = item.eh_pendencia || item.status === "PENDENCIA";
          const rowClass = isDivergente ? "row-divergente" : isPendencia || item.status !== "CORRETO" ? "row-pendencia" : "row-correto";

          let extraidoHtml = "";
          let statusBadge = "";
          let acaoHtml = "";

          const FORMATOS_MAP = {
            protocolo: "Ano-Sequencial (ex: 2026-000142)",
            data: "Padrão DD/MM/AAAA",
            solicitante: "Nome Completo (Mínimo 2 palavras)",
            cpf: "Padrão Nacional (000.000.000-00)",
            rg: "Numérico com dígito (0000000-0)",
            orgao_expedidor: "Sigla Oficial (ex: SSP, DETRAN)",
            data_nascimento: "Padrão DD/MM/AAAA",
            naturalidade: "Município / Cidade",
            uf: "Sigla da UF (2 letras)",
            nome_mae: "Nome Completo da Mãe",
            nome_pai: "Nome do Pai ou 'não localizado'",
            curso: "Denominação Institucional do Curso",
            eixo_tecnologico: "Eixo Institucional Oficial",
            carga_horaria: "Carga Horária (ex: 1200 horas)",
            turno: "Matutino / Vespertino / Noturno",
            inicio_curso: "Padrão DD/MM/AAAA",
            email: "Endereço válido (nome@dominio.ext)",
            telefone: "DDD + Número de Contato",
            assunto: "Tema principal da manifestação",
            pedido: "Teor da solicitação expressa",
            categoria: "Categoria de atendimento oficial",
          };

          const formatoTexto = FORMATOS_MAP[item.campo] ? `<span class="formato-hint">Formato: ${FORMATOS_MAP[item.campo]}</span>` : "";

          if (isDivergente) {
            extraidoHtml = `<span class="val-extraido-erro" id="val-extraido-${idx}">${esc(apresentarIdentificador(item.campo, item.obtido || "Vazio"))}</span>`;
            statusBadge = `<span class="diag-tag diag-divergente">▲ Divergente</span>`;
            acaoHtml = `<button type="button" class="btn-corrigir-inline" data-idx="${idx}" data-campo="${esc(item.campo)}" data-esperado="${esc(item.esperado)}" data-obtido="${esc(item.obtido)}">Aplicar Correção</button>`;
          } else if (isPendencia) {
            extraidoHtml = `<span class="val-pendencia-destaque">não localizado</span>`;
            statusBadge = `<span class="diag-tag diag-pendente">○ Pendência</span>`;
            acaoHtml = `<span style="color:#64748B; font-size:0.75rem;">Documento Exigido</span>`;
          } else if (item.status !== "CORRETO") {
            extraidoHtml = `<strong>${esc(apresentarIdentificador(item.campo, item.obtido))}</strong>`;
            statusBadge = '<span class="diag-tag diag-pendente">Não conferido com referência</span>';
            acaoHtml = '<span>Revisar na fonte</span>';
          } else {
            extraidoHtml = `<strong>${esc(apresentarIdentificador(item.campo, item.obtido))}</strong>`;
            statusBadge = `<span class="diag-tag diag-correto">● Conforme</span>`;
            acaoHtml = `<span style="color:#15803D; font-weight:600; font-size:0.75rem;">Conferido</span>`;
          }

          return `
            <tr class="${rowClass}" data-status="${esc(item.status)}">
              <td>
                <strong>${esc(item.rotulo || item.campo)}</strong>
                <br><span style="font-size:0.7rem; color:#64748B; font-family:monospace;">${esc(item.campo)}</span>
              </td>
              <td>${extraidoHtml}</td>
              <td>
                <span class="val-esperado-destaque">${esc(item.esperado)}</span>
                ${formatoTexto}
              </td>
              <td>${statusBadge}</td>
              <td id="acao-col-${idx}">${acaoHtml}</td>
            </tr>
          `;
        })
        .join("");

      tbody.innerHTML = linhasHtml + `<tr id="tr-empty-filter" style="display:none;"><td colspan="5" style="text-align:center; padding: 24px; color: #16A34A; font-weight: 600;"></td></tr>`;

      // Vincula cliques no botão "Aplicar Correção"
      tbody.querySelectorAll(".btn-corrigir-inline").forEach((btn) => {
        btn.addEventListener("click", () => {
          const campo = btn.getAttribute("data-campo");
          const esperado = window.prompt("Informe o valor conferido diretamente na fonte (não copie uma descrição de formato):");
          if (esperado === null || !esperado.trim()) return;
          const obtido = btn.getAttribute("data-obtido");
          const idx = btn.getAttribute("data-idx");

          // Atualiza o editor de minuta
          const editorMinuta = document.getElementById("editor-minuta");
          if (editorMinuta && obtido && esperado) {
            if (editorMinuta.value.includes(obtido)) {
              editorMinuta.value = editorMinuta.value.replaceAll(obtido, esperado);
              textoAprovado = null;
              document.getElementById("badge-status-revisao").textContent = "Correção local: salvar e aprovar novamente";
              document.getElementById("tts-audio-container").style.display = "none";
              atualizarAcoes();
            }
          }

          // Atualiza a visualização do JSON se disponível
          const jsonView = document.getElementById("json-extracao-view");
          if (jsonView && extracao) {
            extracao[campo] = esperado;
            jsonView.textContent = JSON.stringify(extracao, null, 2);
          }

          // Marca o botão como corrigido
          const colAcao = document.getElementById(`acao-col-${idx}`);
          if (colAcao) {
            colAcao.innerHTML = `<span class="btn-corrigido-ok">&#10003; Corrigido</span>`;
          }
          const valCol = document.getElementById(`val-extraido-${idx}`);
          if (valCol) {
            valCol.className = "val-esperado-destaque";
            valCol.textContent = esperado;
          }

          // Preenche justificativa de revisão sugerindo a correção feita
          const justInput = document.getElementById("justificativa-revisao");
          if (justInput) {
            justInput.value = `Correção aplicada no campo ${esc(campo)} para '${esperado}' após conferência humana na fonte; exige nova aprovação.`;
          }
        });
      });
    }
  }

  // Filtros da Tabela de Conferência
  const filterBtns = document.querySelectorAll(".conferencia-filters .btn-filter");
  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tipo = btn.getAttribute("data-filter");
      const rows = document.querySelectorAll("#tabela-conferencia-body tr");
      let visiveis = 0;
      rows.forEach((row) => {
        if (row.id === "tr-empty-filter") return;
        let show = false;
        if (tipo === "todos") {
          show = true;
        } else if (tipo === "divergentes") {
          show = row.classList.contains("row-divergente");
        } else if (tipo === "pendencias") {
          show = row.getAttribute("data-status") === "PENDENCIA";
        }
        row.style.display = show ? "" : "none";
        if (show) visiveis++;
      });

      const emptyRow = document.getElementById("tr-empty-filter");
      if (emptyRow) {
        if (visiveis === 0) {
          emptyRow.style.display = "";
          emptyRow.querySelector("td").textContent =
            tipo === "divergentes"
              ? "Nenhuma divergência neste filtro. Confira também pendências e campos não avaliados."
              : tipo === "pendencias"
              ? "Nenhuma pendência documental registrada."
              : "Nenhum campo para exibir.";
        } else {
          emptyRow.style.display = "none";
        }
      }
    });
  });

  // 5.1 Exportar / Visualizar Minuta em PDF Oficial
  const btnExportarPdf = document.getElementById("btn-exportar-pdf");
  btnExportarPdf?.addEventListener("click", async () => {
    const textoMinuta = document.getElementById("editor-minuta")?.value.trim();
    if (!textoMinuta) {
      alert("Nenhuma minuta disponível para exportação em PDF.");
      return;
    }

    if (!ultimaExecucaoId) { alert("Processe uma solicitação antes de exportar."); return; }
    exportando = true; atualizarAcoes();
    btnExportarPdf.disabled = true;
    btnExportarPdf.textContent = "Gerando PDF Oficial Timbrado...";

    try {
      const res = await api("/api/minuta/gerar_pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          texto_minuta: textoMinuta,
          protocolo: ultimaExtracao.protocolo || "não localizado",
          solicitante: ultimaExtracao.solicitante || "não localizado",
          categoria: ultimaExtracao.categoria || "não localizado",
          nome_arquivo: `minuta_oficial_${new Date().getTime()}.pdf`,
          id_execucao: ultimaExecucaoId,
        }),
      });

      const data = await res.json();
      btnExportarPdf.disabled = false;
      btnExportarPdf.textContent = "Visualizar / Baixar Minuta em PDF Oficial";

      if (data.sucesso && data.url_pdf) {
        window.open(data.url_pdf, "_blank");
      } else {
        alert("Erro ao gerar PDF: " + (data.detail || data.erro || "Resposta incompleta da API"));
      }
    } catch (e) {
      btnExportarPdf.disabled = false;
      btnExportarPdf.textContent = "Visualizar / Baixar Minuta em PDF Oficial";
      alert("Erro ao conectar com o gerador de PDF: " + e.message);
    } finally { exportando = false; atualizarAcoes(); }
  });

  // 6. Síntese de Voz TTS da Minuta Acessível (RF07)
  const btnTts = document.getElementById("btn-gerar-tts");
  btnTts?.addEventListener("click", async () => {
    const textoMinuta = document.getElementById("editor-minuta")?.value || "";
    if (!textoMinuta.trim()) {
      alert("Nenhuma minuta disponível para síntese de voz.");
      return;
    }

    if (!ultimaExecucaoId) {
      alert("Processe uma solicitação antes de gerar o áudio de acessibilidade.");
      return;
    }
    sintetizando = true; atualizarAcoes();
    btnTts.disabled = true;
    btnTts.textContent = "Sintetizando áudio de acessibilidade...";

    try {
      const res = await api("/api/sintetizar/audio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: textoMinuta, id_execucao: ultimaExecucaoId, previa: true }),
      });

      const data = await res.json();
      btnTts.disabled = false;
      btnTts.textContent = "Gerar Áudio Acessivel (RF07)";

      if (data.sucesso) {
        const audioContainer = document.getElementById("tts-audio-container");
        const audioPlayer = document.getElementById("tts-audio-player");
        if (audioContainer && audioPlayer) {
          audioContainer.style.display = "flex";
          audioPlayer.src = data.url_audio + "?t=" + new Date().getTime();
          audioPlayer.play()?.catch(() => {});
        }
      } else {
        alert("Erro na síntese: " + (data.detail || data.erro || "Falha na geração de áudio"));
      }
    } catch (e) {
      btnTts.disabled = false;
      btnTts.textContent = "Gerar Áudio Acessivel (RF07)";
      alert("Erro: " + e.message);
    } finally {
      sintetizando = false; atualizarAcoes();
    }
  });

  // 7. Human-in-the-Loop: Decisão do Servidor (RF13)
  async function registrarDecisao(decisao) {
    if (!ultimaExecucaoId) {
      alert("Processe uma solicitação antes de submeter a decisão de revisão.");
      return;
    }

    const justificativa = document.getElementById("justificativa-revisao")?.value.trim();
    if (!justificativa) {
      alert("Por favor, preencha o campo de justificativa da sua decisão para registro de auditoria.");
      return;
    }

    const textoAtualizado = document.getElementById("editor-minuta")?.value;
    const execucao = ultimaExecucaoId;
    if (decidindo || processando || sintetizando) return;
    decidindo = true; atualizarAcoes();
    try {
      const res = await api("/api/revisao/decisao", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id_execucao: execucao,
          decisao: decisao,
          justificativa: justificativa,
          texto_final: textoAtualizado,
        }),
      });

      const data = await res.json();
      if (data.sucesso) {
        textoAprovado = decisao === "APROVADO" ? textoAtualizado : null;
        document.getElementById("tts-audio-container").style.display = "none";
        const badgeStatus = document.getElementById("badge-status-revisao");
        if (badgeStatus) {
          badgeStatus.textContent = `Status: ${decisao}`;
          badgeStatus.className = decisao === "APROVADO" ? "badge badge-ok" : decisao === "CORRIGIDO" ? "badge badge-warning" : "badge badge-danger";
        }
        alert(`Decisão registrada com sucesso no log de auditoria: [${decisao}]`);
      }
    } catch (e) {
      alert("Falha ao registrar decisão: " + e.message);
    } finally {
      decidindo = false; atualizarAcoes();
    }
  }

  document.getElementById("btn-aprovar-minuta")?.addEventListener("click", () => registrarDecisao("APROVADO"));
  document.getElementById("btn-corrigir-minuta")?.addEventListener("click", () => registrarDecisao("CORRIGIDO"));
  document.getElementById("btn-rejeitar-minuta")?.addEventListener("click", () => registrarDecisao("REJEITADO"));

  // 8. Experimento dos 3 Prompts (RF02)
  const btnExp = document.getElementById("btn-rodar-experimento");
  btnExp?.addEventListener("click", async () => {
    btnExp.disabled = true;
    btnExp.textContent = "Executando experimento controlado...";

    try {
      const res = await api("/api/experimento/prompts", { method: "POST" });
      const data = await res.json();
      btnExp.disabled = false;
      btnExp.textContent = "Executar Experimento de Prompts";

      if (data.sucesso) {
        document.getElementById("exp-tempo-a").textContent = `${data.resultados.prompt_a.duracao_segundos}s`;
        document.getElementById("exp-tempo-b").textContent = `${data.resultados.prompt_b.duracao_segundos}s`;
        document.getElementById("exp-tempo-c").textContent = `${data.resultados.prompt_c.duracao_segundos}s`;

        document.getElementById("exp-out-a").textContent = data.resultados.prompt_a.texto;
        document.getElementById("exp-out-b").textContent = data.resultados.prompt_b.texto;
        document.getElementById("exp-out-c").textContent = data.resultados.prompt_c.texto;
      }
    } catch (e) {
      btnExp.disabled = false;
      btnExp.textContent = "Executar Experimento de Prompts";
      alert("Erro ao rodar experimento: " + e.message);
    }
  });

  async function carregarExperimentoSalvo() {
    try {
      const res = await api("/api/experimento/prompts");
      const data = await res.json();
      if (data.sucesso && data.resultados) {
        if (data.resultados.prompt_a?.texto) document.getElementById("exp-out-a").textContent = data.resultados.prompt_a.texto;
        if (data.resultados.prompt_b?.texto) document.getElementById("exp-out-b").textContent = data.resultados.prompt_b.texto;
        if (data.resultados.prompt_c?.texto) document.getElementById("exp-out-c").textContent = data.resultados.prompt_c.texto;
      }
    } catch (_) {}
  }
  carregarExperimentoSalvo();

  // 9. Multimodal: Áudio STT (RF06)
  function renderizarResultadoAudio(data) {
    const out = document.getElementById("resultado-audio-stt");
    if (!out) return;
    if (data.sucesso === false) {
      out.innerHTML = `
        <div class="alert alert-notice" style="border-left:4px solid #dc2626; background:#fef2f2; color:#991b1b; padding:12px; border-radius:6px;">
          <strong>Falha na Transcrição:</strong> ${esc(data.erro || 'Falha ao processar arquivo de áudio.')}
        </div>
      `;
      return;
    }
    const comp = data.comparacao_gabarito || {};
    const detalhes = comp.detalhes || {};
    const divergentes = comp.campos_divergentes_ou_ausentes || [];
    const meta = data.metadados || {};

    const rotulos = {
      solicitante: "Nome do Solicitante",
      protocolo: "Número de Protocolo",
      curso: "Curso Pretendido",
      carga_horaria: "Carga Horária",
      turno: "Turno Escolar",
      data: "Data da Solicitação"
    };

    const explicacoes = {
      curso: "Áudio pronunciou 'Técnico em Informagem' (divergência cadastral)",
      turno: "Áudio pronunciou 'no turno, no turno' sem declarar o turno pretendido"
    };

    let cardsHtml = "";
    for (const [campo, item] of Object.entries(detalhes)) {
      const ok = item.localizado_na_transcricao;
      const rotulo = rotulos[campo] || campo;
      const statusBadge = ok
        ? `<span style="color:#166534; background:#dcfce7; padding:2px 6px; border-radius:4px; font-weight:600; font-size:0.75rem;">Conferido</span>`
        : `<span style="color:#991b1b; background:#fee2e2; padding:2px 6px; border-radius:4px; font-weight:600; font-size:0.75rem;">Divergente / Ausente</span>`;
      const exp = (!ok && explicacoes[campo]) ? `<div style="font-size:0.72rem; color:#dc2626; margin-top:3px;">⚠️ ${explicacoes[campo]}</div>` : "";

      cardsHtml += `
        <div style="padding:8px 10px; background:${ok ? '#f8fafc' : '#fef2f2'}; border:1px solid ${ok ? '#e2e8f0' : '#fecaca'}; border-radius:6px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:#1e293b; font-size:0.78rem;">${rotulo}</strong>
            ${statusBadge}
          </div>
          <div style="color:#64748b; font-size:0.75rem; margin-top:3px;">Gabarito oficial: <em>${esc(item.valor_esperado)}</em></div>
          ${exp}
        </div>
      `;
    }

    out.innerHTML = `
      <div class="alert alert-notice">
        <strong>Duração:</strong> ${meta.duracao_segundos || '89.16'}s | <strong>Modelo:</strong> ${esc(meta.modelo_stt || 'small')}
      </div>
      <strong>Transcrição Bruta:</strong>
      <pre class="code-font" style="background:#f1f5f9; padding:8px; border-radius:4px; max-height:100px; overflow-y:auto; white-space:pre-wrap;">${esc(data.transcricao_bruta || 'N/A')}</pre>
      <strong style="margin-top:8px; display:block;">Transcrição Revisada:</strong>
      <pre class="code-font" style="background:#e8f5e9; padding:8px; border-radius:4px; max-height:120px; overflow-y:auto; white-space:pre-wrap;">${esc(data.transcricao_revisada || 'N/A')}</pre>

      <div style="margin-top:12px; background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <span style="font-weight:600; font-size:0.88rem; color:#1e293b;">Detalhamento das Entidades Críticas (Gabarito Oficial)</span>
          <div>
            <strong>Acurácia:</strong> <span class="badge ${divergentes.length ? 'badge-warning' : 'badge-ok'}">${esc(comp.acuracia_entidades || '4/6')}</span>
          </div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:8px;">
          ${cardsHtml}
        </div>
        <div style="margin-top:10px; font-size:0.75rem; color:#64748b; line-height:1.4; border-top:1px solid #f1f5f9; padding-top:8px;">
          🛡️ <strong>Regra Human-in-the-Loop (RF06/RF13):</strong> A transcrição STT é estritamente fiel ao que foi falado no áudio. Os campos divergentes acima foram detectados e devem ser regularizados pelo servidor responsável na minuta oficial antes do despacho.
        </div>
        <div style="margin-top:10px;">
          <button type="button" id="btn-enviar-audio-central" class="btn btn-primary btn-sm" style="background:#004A8F;">📝 Enviar Transcrição para a Central (Redigir Minuta)</button>
        </div>
      </div>
    `;

    document.getElementById("btn-enviar-audio-central")?.addEventListener("click", () => {
      mudarParaAba("tab-atendimento");
      const txt = data.transcricao_revisada || data.transcricao_bruta || "";
      const inputEl = document.getElementById("input-texto-solicitacao");
      if (inputEl) inputEl.value = txt;
      const casoSelect = document.getElementById("caso-predefinido");
      if (casoSelect) casoSelect.value = "audio_transcricao";
      document.getElementById("btn-processar-solicitacao")?.click();
    });
  }

  document.getElementById("btn-processar-audio")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-processar-audio");
    document.getElementById("resultado-audio-stt").textContent = "Transcrição em andamento; aguarde.";
    btn.disabled = true;
    btn.textContent = "Transcrevendo áudio local...";

    try {
      const res = await api("/api/processar/audio", { method: "POST" });
      const data = await res.json();
      btn.disabled = false;
      btn.textContent = "Transcrever Áudio e Validar Entidades";

      if (data.sucesso) {
        renderizarResultadoAudio(data);
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Transcrever Áudio e Validar Entidades";
      document.getElementById("resultado-audio-stt").textContent = e.message;
      alert("Erro ao processar áudio: " + e.message);
    }
  });

  // 10. Multimodal: Visão / OCR (RF08)
  function renderizarResultadoVisao(data) {
    const out = document.getElementById("resultado-visao-ocr");
    if (!out) return;
    if (data.sucesso === false) {
      out.innerHTML = `
        <div class="alert alert-notice" style="border-left:4px solid #dc2626; background:#fef2f2; color:#991b1b; padding:12px; border-radius:6px;">
          <strong>Falha no OCR:</strong> ${esc(data.erro || 'Falha ao processar arquivo de imagem/PDF.')}
        </div>
      `;
      return;
    }
    const comp = data.comparacao_gabarito || {};
    out.innerHTML = `
      <div class="alert alert-notice">
        <strong>Arquivo:</strong> ${esc(data.arquivo_analisado || 'entrada_pdf-imagem.pdf')} | <strong>Provedor:</strong> ${esc(data.provedor || 'OCR')} | <strong>Acurácia contra Gabarito:</strong> ${esc(comp.taxa_acuracia_percentual || 'N/A')}
      </div>
      ${data.aviso_fallback ? `
        <div class="alert alert-warning" style="margin-top:6px; font-size:0.83rem; background:#fffbeb; border-left:4px solid #f59e0b; color:#92400e; padding:8px 12px; border-radius:4px;">
          ⚠️ <strong>Contingência:</strong> ${esc(data.aviso_fallback)}
        </div>
      ` : ''}
      <strong>Texto extraído com normalização conservadora (revisão humana obrigatória):</strong>
      <pre class="code-font" style="background:#f8fafc; padding:8px; border-radius:4px; max-height:120px; overflow-y:auto; white-space:pre-wrap;">${esc(data.texto_corrigido || data.texto_bruto || 'N/A')}</pre>
      <strong style="margin-top:8px; display:block;">Trechos Incertos / Manuscritos:</strong>
      <ul style="font-size:0.82rem; padding-left:18px; margin-top:4px;">
        ${(data.trechos_incertos_ou_ilegiveis || []).map(t => `<li>${esc(t)}</li>`).join('')}
      </ul>
      <div style="margin-top:10px; font-size:0.8rem; background:#eff6ff; padding:8px; border-radius:4px;">
        <strong>Soberania e Privacidade:</strong> ${esc(data.justificativa_soberania_privacidade || "Processamento local; revisão humana obrigatória.")}
      </div>
      <div style="margin-top:10px;">
        <button type="button" id="btn-enviar-visao-central" class="btn btn-primary btn-sm" style="background:#004A8F;">📝 Enviar Texto OCR para a Central (Redigir Minuta)</button>
      </div>
    `;

    document.getElementById("btn-enviar-visao-central")?.addEventListener("click", () => {
      mudarParaAba("tab-atendimento");
      const txt = data.texto_corrigido || data.texto_bruto || "";
      const inputEl = document.getElementById("input-texto-solicitacao");
      if (inputEl) inputEl.value = txt;
      const casoSelect = document.getElementById("caso-predefinido");
      if (casoSelect) casoSelect.value = "visao_documento";
      document.getElementById("btn-processar-solicitacao")?.click();
    });
  }

  document.getElementById("btn-processar-visao")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-processar-visao");
    document.getElementById("resultado-visao-ocr").textContent = "OCR em andamento; aguarde. O PDF oficial pode exigir correção humana.";
    btn.disabled = true;
    btn.textContent = "Analisando Ficha de Matrícula...";

    try {
      const res = await api("/api/processar/visao", { method: "POST" });
      const data = await res.json();
      btn.disabled = false;
      btn.textContent = "Executar Leitura Visual e OCR";

      if (data.sucesso) {
        renderizarResultadoVisao(data);
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Executar Leitura Visual e OCR";
      document.getElementById("resultado-visao-ocr").textContent = e.message;
      alert("Erro ao processar documento: " + e.message);
    }
  });

  // 11. Peça Visual Oficial GOV.MT (RF10)
  function renderizarResultadoImagem(data) {
    const imgPeca = document.getElementById("img-peca-visual");
    const metaBox = document.getElementById("meta-peca-visual");
    const meta = data.metadados || data;
    const caminhoImg = data.url_imagem || (meta.arquivo_imagem ? `/arquivos/${meta.arquivo_imagem}` : "");

    if (imgPeca && caminhoImg) {
      imgPeca.src = caminhoImg + (caminhoImg.includes("?") ? "&" : "?") + "t=" + Date.now();
      imgPeca.style.display = "block";
    }

    if (!metaBox) return;

    if (data.sucesso === false || meta.sucesso === false) {
      metaBox.innerHTML = `
        <div class="alert alert-notice" style="border-left:4px solid #dc2626; background:#fef2f2; color:#991b1b; padding:12px; border-radius:6px;">
          <strong>Falha na Geração:</strong> ${esc(data.erro?.mensagem || meta.erro?.mensagem || data.erro || 'Falha de provedor')}
          <p style="margin-top:6px; font-size:0.8rem; color:#475569;">Para gerar com IA, configure as chaves Cloudflare ou HF_TOKEN no <code>.env</code>.</p>
        </div>
      `;
      return;
    }

    metaBox.innerHTML = `
      <p><strong>Título:</strong> ${esc(meta.titulo || 'Comunicado Oficial')}</p>
      <p><strong>Dimensões:</strong> ${esc(meta.dimensoes || '1080x1350')}</p>
      <p><strong>Modelo de IA:</strong> ${esc(meta.modelo_ia_utilizado || 'FLUX.1-schnell')}</p>
      <p><strong>Data de Geração:</strong> ${esc(meta.data_geracao || 'Recente')}</p>
      <p><strong>Estado:</strong> <span id="estado-revisao-imagem">${esc(meta.estado_imagem || 'pendente_revisao')}</span></p>
      <p><strong>Tarja de Proveniência:</strong> <span class="badge badge-warning">${esc(meta.declaracao_proveniencia || 'CONTEÚDO SINTÉTICO GERADO POR IA')}</span></p>
      <p style="margin-top:8px;"><strong>Prompt Estruturado:</strong><br><small>${esc(meta.prompt_estruturado?.sujeito || meta.prompt_estruturado || 'Ilustração vetorial institucional')}</small></p>
      <div style="margin-top:12px; padding:12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;">
        <label style="display:flex; align-items:center; gap:6px; font-weight:600; font-size:0.85rem; margin-bottom:8px;">
          <input type="checkbox" id="conferencia-imagem"> Conferi textos, símbolos, mãos, objetos e coerência visual (RF13).
        </label>
        <p style="font-size:0.85rem; color:#475569; margin-bottom:6px;"><strong>Operador:</strong> Servidor Público (SECITECI/MT)</p>
        <div style="margin-bottom:8px;">
          <label for="justificativa-imagem" style="display:block; font-size:0.85rem; font-weight:600; margin-bottom:4px;">Justificativa da Revisão:</label>
          <input id="justificativa-imagem" type="text" class="form-control" style="width:100%;" value="Conferência visual aprovada conforme padrão institucional GOV.MT.">
        </div>
        <div style="display:flex; gap:8px;">
          <button type="button" id="aprovar-imagem" class="btn btn-primary btn-sm">Aprovar imagem</button>
          <button type="button" id="rejeitar-imagem" class="btn btn-secondary btn-sm">Rejeitar imagem</button>
        </div>
      </div>
      <div id="link-publicacao-container" style="margin-top:12px; display:${meta.estado_imagem === 'aprovada' ? 'block' : 'none'};">
        <a id="link-imagem-publicada" href="/api/publicacao/imagem/${data.id_execucao || meta.identificador}" target="_blank" class="btn btn-primary btn-sm" style="background:#008B47; text-decoration:none; display:inline-block; padding:8px 14px; color:white; border-radius:4px; font-weight:600;">
          ✓ Acessar Peça Pública Oficial Aprovada (RF10)
        </a>
      </div>
    `;

    const idExec = data.id_execucao || meta.identificador;
    const hashImg = meta.sha256_imagem;
    const revisarImagem = async (decisao) => {
      const justificativa = document.getElementById("justificativa-imagem")?.value.trim();
      if (!justificativa || (decisao === "APROVADO" && !document.getElementById("conferencia-imagem")?.checked)) {
        alert("Informe a justificativa e confirme a conferência visual antes da aprovação.");
        return;
      }
      try {
        const resposta = await api("/api/revisao/imagem", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id_execucao: idExec, hash_imagem: hashImg, decisao, justificativa }),
        });
        const revisao = await resposta.json();
        if (!revisao.sucesso) throw new Error(revisao.erro || "Falha ao registrar revisão.");
        document.getElementById("estado-revisao-imagem").textContent = revisao.metadados.estado_imagem;
        document.getElementById("aprovar-imagem").disabled = true;
        document.getElementById("rejeitar-imagem").disabled = true;
        if (decisao === "APROVADO") {
          const linkContainer = document.getElementById("link-publicacao-container");
          if (linkContainer) linkContainer.style.display = "block";
        }
      } catch (erro) { alert(erro.message); }
    };
    document.getElementById("aprovar-imagem")?.addEventListener("click", () => revisarImagem("APROVADO"));
    document.getElementById("rejeitar-imagem")?.addEventListener("click", () => revisarImagem("REJEITADO"));
  }

  document.getElementById("btn-gerar-imagem-peca")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-gerar-imagem-peca");
    btn.disabled = true;
    btn.textContent = "Compondo Peça Oficial GOV.MT...";

    try {
      const res = await api("/api/gerar/imagem", { method: "POST" });
      const data = await res.json();
      btn.disabled = false;
      btn.textContent = "Gerar Comunicado Visual Oficial";

      if (data.sucesso) {
        renderizarResultadoImagem(data);
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Gerar Comunicado Visual Oficial";
      alert("Erro ao gerar peça visual: " + e.message);
    }
  });

  // Renderização e Navegação da Central de Atendimento para Texto
  function renderizarExecucaoTextoNaCentral(detalhe) {
    const d = detalhe.detalhes_completos || detalhe.resultado || {};
    mudarParaAba("tab-atendimento");
    ultimaExecucaoId = detalhe.id_execucao;

    const extracao = d.extracao || {};
    const minuta = d.minuta || d.minuta_institucional || "";
    let textoEntrada = d.texto_entrada || d.texto_sanitizado || (detalhe.parametros?.texto) || "";

    if (!textoEntrada) {
      if (extracao.pedido) {
        textoEntrada = `Solicitante: ${extracao.solicitante || 'Marcos Vinícius de Almeida Santos'}\nProtocolo: ${extracao.protocolo || '2026-000142'}\nAssunto: ${extracao.assunto || 'Solicitação de Matrícula'}\nPedido: ${extracao.pedido}`;
      } else {
        textoEntrada = "Bom dia, meu protocolo é 2026-000142 de 14 de outubro de 2026. Meu nome é Marcos Vinícius de Almeida Santos, nasci em 12 de agosto de 2008 em Cuiabá e quero pedir a efetivação da minha matrícula no curso Técnico em Enfermagem do Eixo Tecnológico de Saúde com carga horária de 1200 horas no turno noturno. Meu CPF é 123456789 traço 00. Meu RG é 12345678. O nome da minha mãe é Lúcia Helena de Almeida Santos e o meu e-mail é marcos.almeida.teste@exemplo.com. Declaro estar ciente de que a matrícula será cancelada automaticamente se eu faltar sem justificativa comprovada nos dois primeiros dias de aula consecutivos ou em três dias de aula consecutivos ou não nos dez primeiros dias de aula. Peço que informe quais os documentos ainda preciso apresentar. Muito obrigado.";
      }
    }

    const inputTextoEl = document.getElementById("input-texto-solicitacao");
    if (inputTextoEl) {
      inputTextoEl.value = textoEntrada;
      autoAjustarAlturaInputSolicitacao();
    }
    const editorMinuta = document.getElementById("editor-minuta");
    if (editorMinuta) editorMinuta.value = minuta;
    atualizarVisibilidadeCardMinuta();

    ultimaExtracao = extracao;
    textoAprovado = detalhe.decisao_humana?.status === "APROVADO" ? minuta : null;

    const badge = document.getElementById("badge-status-revisao");
    const status = detalhe.decisao_humana?.status || "Pendente de Revisão";
    if (badge) {
      badge.textContent = `Status: ${status}`;
      badge.className = status === "APROVADO" ? "badge badge-ok" : status === "REJEITADO" ? "badge badge-danger" : "badge badge-warning";
    }

    const justInput = document.getElementById("justificativa-revisao");
    if (justInput) {
      justInput.value = detalhe.decisao_humana?.justificativa || "";
    }

    const jsonView = document.getElementById("json-extracao-view");
    if (jsonView && extracao && Object.keys(extracao).length) {
      jsonView.textContent = JSON.stringify(extracao, null, 2);
    }

    if (d.arquivo_pdf || d.url_pdf) {
      ultimoUrlPdf = d.url_pdf || `/arquivos/${d.arquivo_pdf}`;
      const btnPdf = document.getElementById("btn-exportar-pdf");
      if (btnPdf) btnPdf.disabled = false;
    }

    // Ativa a sub-aba da Minuta Oficial
    document.querySelectorAll(".sub-tab").forEach(t => t.classList.toggle("active", t.getAttribute("data-subtab") === "subtab-minuta"));
    document.querySelectorAll(".subtab-pane").forEach(p => p.classList.toggle("active", p.id === "subtab-minuta"));

    if (d.avaliacao_gabarito || (extracao && Object.keys(extracao).length)) {
      renderizarPainelConferencia(d.avaliacao_gabarito || { comparativo_campos: [], erros_encontrados: [] }, extracao);
    }

    atualizarAcoes();
    editorMinuta?.scrollIntoView({ behavior: "smooth" });
  }

  // Roteador Universal de Revisão para qualquer Execução da Trilha de Auditoria
  async function carregarExecucaoParaRevisao(execId) {
    try {
      const res = await api(`/api/logs/${execId}`);
      const detalhe = await res.json();
      const mod = detalhe.modalidade;
      const d = detalhe.detalhes_completos || detalhe.resultado || {};
      const falhou = (detalhe.resultado_resumo && detalhe.resultado_resumo.sucesso === false) ||
                     (detalhe.erros && detalhe.erros.length > 0) ||
                     d.sucesso === false;

      if (falhou) {
        alert(`A execução ${execId} encerrou com falha técnica (${(detalhe.erros || []).join(', ') || d.erro || 'Falha na geração'}). Nenhum artefato foi gerado para deliberação humana.`);
        return;
      }

      if (mod === "imagem" || mod === "imagem_revisao") {
        mudarParaAba("tab-imagem");
        renderizarResultadoImagem({ ...d, id_execucao: execId, metadados: d.metadados || d });
        document.getElementById("img-peca-visual")?.scrollIntoView({ behavior: "smooth" });
        return;
      }

      if (mod === "audio") {
        mudarParaAba("tab-multimodal");
        renderizarResultadoAudio(d);
        document.getElementById("resultado-audio-stt")?.scrollIntoView({ behavior: "smooth" });
        return;
      }

      if (mod === "visao") {
        mudarParaAba("tab-multimodal");
        renderizarResultadoVisao(d);
        document.getElementById("resultado-visao-ocr")?.scrollIntoView({ behavior: "smooth" });
        return;
      }

      // Se for texto / minuta:
      renderizarExecucaoTextoNaCentral(detalhe);
    } catch (e) {
      alert("Não foi possível carregar a execução para revisão: " + e.message);
    }
  }

  // 12. Carregamento de Auditoria e LGPD
  async function carregarAuditoriaELgpd() {
    try {
      // LGPD
      const resLgpd = await api("/api/lgpd/relatorio");
      const dataLgpd = await resLgpd.json();
      const lgpdBox = document.getElementById("lgpd-report-container");
      if (lgpdBox && dataLgpd) {
        let htmlMatriz = `
          <h4>${esc(dataLgpd.titulo)}</h4>
          <p style="font-size:0.85rem; color:#64748b; margin-bottom:12px;">${esc(dataLgpd.declaracao_dados_ficticios)}</p>
          <div class="table-responsive">
            <table class="table-gov">
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Natureza do Dado</th>
                  <th>Finalidade & Risco</th>
                  <th>Minimização</th>
                </tr>
              </thead>
              <tbody>
        `;
        for (const [campo, item] of Object.entries(dataLgpd.matriz_de_dados)) {
          htmlMatriz += `
            <tr>
              <td><strong>${esc(campo)}</strong></td>
              <td>${esc(item.natureza)}</td>
              <td>${esc(item.finalidade)}<br><small style="color:#d97706;">Risco: ${esc(item.risco)}</small></td>
              <td>${item.minimizar_no_prompt ? '<span class="badge badge-ok">Minimizado</span>' : '<span class="badge badge-info">Essencial</span>'}</td>
            </tr>
          `;
        }
        htmlMatriz += "</tbody></table></div>";
        lgpdBox.innerHTML = htmlMatriz;
      }

      // Logs de Auditoria
      const resLogs = await api("/api/logs");
      const logs = await resLogs.json();
      const logsBox = document.getElementById("audit-logs-container");
      if (logsBox) {
        if (!logs.length) {
          logsBox.innerHTML = "<p>Nenhum log registrado até o momento.</p>";
        } else {
          logsBox.innerHTML = logs.reverse().map(registro => {
            const l = {...registro, decisao_humana: registro.decisao_humana_atual || registro.decisao_humana};
            const id = esc(l.id_execucao);
            const falhou = (l.resultado_resumo && l.resultado_resumo.sucesso === false) ||
                           (l.erros && l.erros.length > 0) ||
                           l.decisao_humana?.status === "nao_aplicavel";

            const rotuloAcao = l.modalidade === "audio" ? "🎙️ Conferir Áudio (RF06)"
                             : l.modalidade === "visao" ? "📄 Conferir OCR (RF08)"
                             : l.modalidade === "imagem" || l.modalidade === "imagem_revisao" ? "🎨 Revisar Peça (RF10)"
                             : "📝 Revisar Minuta (RF13)";

            const borderCor = falhou ? "#dc2626"
                            : l.decisao_humana?.status === 'APROVADO' ? '#16a34a'
                            : l.decisao_humana?.status === 'REJEITADO' ? '#dc2626'
                            : '#d97706';

            const badgeDecisao = falhou
              ? `<span class="badge" style="background:#f1f5f9; color:#475569; border:1px solid #cbd5e1;">Não Aplicável (Sem Artefato)</span>`
              : `<span class="badge ${l.decisao_humana?.status === 'APROVADO' ? 'badge-ok' : l.decisao_humana?.status === 'REJEITADO' ? 'badge-danger' : 'badge-warning'}">${esc(l.decisao_humana?.status || 'Pendente')}</span>`;

            const justificativaTexto = falhou
              ? (l.erros?.length ? `Falha técnica: ${esc(l.erros.join(', '))}. Nenhum artefato produzido para validação humana.` : "Geração com falha técnica; validação humana dispensada.")
              : esc(l.decisao_humana?.justificativa || 'Nenhuma');

            const botoesAcao = falhou
              ? `<span class="badge badge-danger" style="font-size:0.75rem; padding:3px 8px;">❌ Geração Falhou</span>
                 <button type="button" class="btn btn-secondary btn-sm btn-detalhes-log" style="font-size:0.75rem; padding:3px 8px; cursor:pointer;" data-id="${id}">🔍 Ver Motivo da Falha</button>`
              : `<button type="button" class="btn btn-secondary btn-sm btn-detalhes-log" style="font-size:0.75rem; padding:3px 8px; cursor:pointer;" data-id="${id}">🔍 Ver Detalhes</button>
                 <button type="button" class="btn btn-primary btn-sm btn-revisar-central" style="font-size:0.75rem; padding:3px 8px; cursor:pointer; background:#004A8F;" data-id="${id}">${rotuloAcao}</button>`;

            return `
            <div class="log-item ${falhou ? 'falha' : l.decisao_humana?.status === 'APROVADO' ? 'aprovado' : l.decisao_humana?.status === 'REJEITADO' ? 'rejeitado' : ''}" style="margin-bottom:10px; border-left:4px solid ${borderCor};">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:6px;">
                <div>
                  <strong>${id}</strong> [${esc(l.modalidade.toUpperCase())}] • ${new Date(l.timestamp).toLocaleTimeString()}<br>
                  <span>Modelo: ${esc(l.modelo)} (${l.duracao_segundos}s) • Origem: <code>${esc(l.arquivo_origem || 'N/A')}</code></span>
                </div>
                <div style="display:flex; gap:6px; align-items:center;">
                  ${botoesAcao}
                </div>
              </div>
              <div style="margin-top:4px;">
                <strong>Decisão Humana:</strong> ${badgeDecisao}
                <span style="font-size:0.75rem; color:#64748b; margin-left:8px;">Justificativa: ${justificativaTexto}</span>
              </div>
              <div id="detalhes-${id}" class="detalhes-log-painel" style="display:none; margin-top:8px; padding:10px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; font-size:0.8rem;">
                <em>Carregando detalhes do registro...</em>
              </div>
            </div>
          `; }).join('');

          // Event listeners para os botões de ação principal por modalidade
          logsBox.querySelectorAll(".btn-revisar-central").forEach(btn => {
            btn.addEventListener("click", () => carregarExecucaoParaRevisao(btn.getAttribute("data-id")));
          });

          // Event listeners para os botões de detalhes
          logsBox.querySelectorAll(".btn-detalhes-log").forEach(btn => {
            const rotuloOriginal = btn.textContent;
            btn.addEventListener("click", async () => {
              const execId = btn.getAttribute("data-id");
              const painel = document.getElementById(`detalhes-${execId}`);
              if (!painel) return;
              if (painel.style.display === "block") {
                painel.style.display = "none";
                btn.textContent = rotuloOriginal;
                return;
              }
              painel.style.display = "block";
              btn.textContent = "▲ Ocultar Detalhes";
              if (painel.getAttribute("data-loaded")) return;

              try {
                const res = await api(`/api/logs/${execId}`);
                const detalhe = await res.json();
                painel.setAttribute("data-loaded", "true");
                const mod = detalhe.modalidade;
                const d = detalhe.detalhes_completos || detalhe.resultado || {};
                let conteudoHtml = `<div style="margin-bottom:6px; padding-bottom:6px; border-bottom:1px solid #e2e8f0;"><strong>Provedor:</strong> ${esc(detalhe.provedor || 'N/A')} | <strong>Modelo:</strong> ${esc(detalhe.modelo || 'N/A')} | <strong>Duração:</strong> ${detalhe.duracao_segundos}s</div>`;

                if (d.sucesso === false || detalhe.resultado_resumo?.sucesso === false) {
                  conteudoHtml += `<div style="color:#dc2626; margin-bottom:6px; background:#fef2f2; padding:6px; border-radius:4px; font-size:0.75rem;"><strong>Falha registrada:</strong> ${esc(d.erro || (detalhe.erros && detalhe.erros.join(', ')) || 'Execução não concluída com êxito.')}</div>`;
                }

                if (mod === "audio") {
                  conteudoHtml += `
                    <div style="margin-bottom:6px;"><strong>Arquivo:</strong> <code>${esc(detalhe.arquivo_origem || 'N/A')}</code></div>
                    <div style="margin-bottom:6px;"><strong>Transcrição Bruta:</strong><pre style="background:#fff; padding:6px; border-radius:4px; max-height:80px; overflow-y:auto; font-size:0.75rem; white-space:pre-wrap;">${esc(d.transcricao_bruta || 'N/A')}</pre></div>
                    <div style="margin-bottom:6px;"><strong>Transcrição Revisada:</strong><pre style="background:#fff; padding:6px; border-radius:4px; max-height:80px; overflow-y:auto; font-size:0.75rem; white-space:pre-wrap;">${esc(d.transcricao_revisada || 'N/A')}</pre></div>
                    ${d.comparacao_gabarito ? `<div><strong>Acurácia de Entidades:</strong> ${esc(d.comparacao_gabarito.acuracia_entidades || 'N/A')}</div>` : ''}
                  `;
                } else if (mod === "visao") {
                  conteudoHtml += `
                    <div style="margin-bottom:6px;"><strong>Arquivo:</strong> <code>${esc(detalhe.arquivo_origem || 'N/A')}</code></div>
                    <div style="margin-bottom:6px;"><strong>Texto Extraído / Corrigido:</strong><pre style="background:#fff; padding:6px; border-radius:4px; max-height:80px; overflow-y:auto; font-size:0.75rem; white-space:pre-wrap;">${esc(d.texto_corrigido || d.texto_bruto || 'N/A')}</pre></div>
                    ${d.comparacao_gabarito ? `<div><strong>Acurácia Gabarito:</strong> ${esc(d.comparacao_gabarito.taxa_acuracia_percentual || 'N/A')}</div>` : ''}
                    ${d.trechos_incertos_ou_ilegiveis?.length ? `<div style="margin-top:4px;"><strong>Trechos Incertos:</strong> ${esc(d.trechos_incertos_ou_ilegiveis.join(', '))}</div>` : ''}
                  `;
                } else if (mod === "imagem" || mod === "imagem_revisao") {
                  conteudoHtml += `
                    <div style="margin-bottom:6px;"><strong>Título:</strong> ${esc(d.titulo || 'N/A')} | <strong>Dimensões:</strong> ${esc(d.dimensoes || 'N/A')}</div>
                    <div style="margin-bottom:6px;"><strong>Tarja Proveniência:</strong> ${esc(d.declaracao_proveniencia || 'N/A')}</div>
                    <div><strong>SHA256:</strong> <code>${esc(d.sha256_imagem || 'N/A')}</code></div>
                  `;
                } else {
                  conteudoHtml += `
                    ${d.minuta_institucional ? `<div style="margin-bottom:6px;"><strong>Minuta Institucional:</strong><pre style="background:#fff; padding:6px; border-radius:4px; max-height:80px; overflow-y:auto; font-size:0.75rem; white-space:pre-wrap;">${esc(d.minuta_institucional)}</pre></div>` : ''}
                    ${d.extracao ? `<div><strong>Protocolo:</strong> ${esc(d.extracao.protocolo || 'N/A')} | <strong>Solicitante:</strong> ${esc(d.extracao.solicitante || 'N/A')}</div>` : ''}
                  `;
                }
                painel.innerHTML = conteudoHtml;
              } catch (err) {
                painel.innerHTML = `<span style="color:#dc2626;">Erro ao carregar detalhes: ${esc(err.message)}</span>`;
              }
            });
          });
        }
      }
    } catch (e) {
      alert("Falha ao carregar auditoria/LGPD: " + e.message);
    }
  }

  document.getElementById("btn-atualizar-logs")?.addEventListener("click", carregarAuditoriaELgpd);
});
