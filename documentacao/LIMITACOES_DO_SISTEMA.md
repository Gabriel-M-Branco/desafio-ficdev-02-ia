# Limitações do Sistema

**Projeto:** Central Inteligente de Atendimento e Consulta Institucional (GOV.MT / SECITECI-MT)  
**Versão:** 2.0.0 | **Interface Oficial:** Streamlit (`src/app.py`)

---

### 1. Modelos de IA e Infraestrutura Textual
- **Sem LLM Neural Local:** Não há execução local de modelos de linguagem de grande porte (7B a 70B parâmetros) por pesos (ex.: Ollama ou vLLM), devido aos requisitos de hardware (40 a 80 GB de VRAM).
- **Dependência de APIs para Geração:** A geração textual fluida depende de provedores em nuvem (OpenAI, Hugging Face ou OpenRouter).
- **Operação sem Chave (`.env`):** Na ausência de chaves, o sistema não simula conexão externa; opera em modo local por regras determinísticas e adaptador simulado identificado (`RF21`).

### 2. Base de Conhecimento e RAG
- **Acervo Delimitado:** O RAG consulta exclusivamente os 6 documentos institucionais fictícios indexados (`DOC-SECITECI-001` a `006`). Não há busca em fontes externas.
- **Abstenção Obrigatória:** Se a evidência for insuficiente (`P6`, `P7`), o sistema declara a falta de dados e transfere a demanda para atendimento humano.
- **Conflitos Normativos:** Havendo divergência entre normas (`P8`), o sistema não decide a prevalência; cita ambas as regras e solicita decisão de um servidor.

### 3. Guardrails e Parâmetros Operacionais
- **Entrada Textual:** Máximo de 8.000 caracteres por solicitação.
- **Arquivos:** Máximo de 10 MB nos formatos `.txt`, `.pdf`, `.png`, `.jpg`, `.jpeg`, `.mp3`, `.wav` e `.m4a`.
- **Controle de Custo e Execução:** Limite de 8 chamadas a modelos por execução e até 2.048 tokens por chamada.
- **Escopo e Segurança:** Bloqueio de temas fora do escopo educacional/institucional e neutralização de tentativas de injeção de instruções e exfiltração de chaves (`ADV-01` a `ADV-03`).

### 4. Governança e Autonomia
- **Human-in-the-Loop Obrigatório:** Nenhuma minuta, despacho ou ato administrativo é finalizado sem validação humana.
- **Trava de Áudio e Imagem:** A síntese de voz acessível exige texto previamente aprovado por servidor; a publicação de artes exige conferência de hash SHA-256.
- **Alucinação Zero:** Dados cadastrais não informados permanecem como `"não localizado"` / `null`, com separação estrita entre dados literais e inferidos.

### 5. Motores Multimodais Locais e Conectados
- **Áudio STT:** `faster-whisper` (`small`/int8 em CPU) é a opção soberana local que pode requerer revisão em áudios com muito ruído; quando conectado, o sistema dispõe da API `whisper-1` para maior acurácia fonética.
- **Visão / OCR:** O motor local `Tesseract` (`por`) com `PyMuPDF` possui menor acurácia em documentos manuscritos ou de baixa resolução; a integração com `gpt-4o` Vision (`detail: high`) mitiga essa limitação para extração de alta fidelidade em formulários escaneados.
- **Voz TTS:** `SAPI5` depende de vozes instaladas no Windows; `edge-tts` e `OpenAI TTS` dependem de conexão com a rede, ambos submetidos à trava de aprovação humana prévia do texto.

---

### Quadro Resumo

| Área | Limitação | Mitigação Adotada |
|---|---|---|
| **Texto / LLM** | Sem LLM pesado local | Modo local determinístico explícito e chave configurável |
| **RAG** | Acervo de 6 documentos | Citação estrita, abstenção declarada e detecção de conflitos |
| **Segurança** | Injeção e estouro de cota | Guardrails de tamanho, escopo e envelopes XML |
| **Decisão** | Sem autoridade pública | Validação humana obrigatória (*Human-in-the-Loop*) |
| **Dados** | Omissões pelo cidadão | Marcação de "não localizado", sem preenchimento fictício |
