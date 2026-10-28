# AGENTS.md - Diretrizes Arquiteturais e Regras do Agente



## 1. Visão Geral do Projeto

Protótipo da **Central Inteligente de Atendimento e Comunicação Institucional** (Desafio Prático 1 - FIC_DEV), compatível com os padrões visuais e institucionais do **GOV.MT**.

O sistema processa solicitações fictícias em **texto, áudio e imagem**, extrai dados estruturados (JSON), gera minutas institucionais seguras, sintetiza voz para acessibilidade (TTS), gera peças visuais padronizadas (abordagem híbrida IA + template programático) e oferece uma **Interface Web (HTML/CSS/JS)** para revisão humana (*Human-in-the-loop*) e auditoria completa.



## 2. Stack Tecnológica Definida (Provedores Configuráveis / Custo Não Presumido)

- **Linguagem & Ponto de Entrada:** Python 3.11+ acionado via `python -m src.main` (que sobe o servidor FastAPI com a interface web por padrão ou roda o modo CLI/experimento via flags `--cli` / `--run-all`).

- **Backend & Interface Humana:** `FastAPI` + `Uvicorn` servindo um frontend limpo em **HTML5, CSS3 e JavaScript (Vanilla)** (painel do servidor público para aprovar, rejeitar, editar ou regenerar extrações e minutas).

- **Provedor Principal de IA:** **Hugging Face Serverless Inference API** (`huggingface_hub` / `InferenceClient`) usando `HF_TOKEN`:

  - **LLM (Texto/Extração/Minuta):** `Qwen/Qwen2.5-72B-Instruct` ou `meta-llama/Llama-3.3-70B-Instruct`.

  - **Visão/OCR (RF08):** PyMuPDF + Tesseract português local; alternativas PSM e regiões, sem preenchimento inventado.

  - **Áudio STT (RF06):** faster-whisper local small/CPU/int8/pt ou whisper via HF, com provedores configuráveis.

  - **Imagem (RF10 - Abordagem Híbrida):** Cloudflare Workers AI FLUX ou HF/endpoint configurável (gera apenas a arte/ilustração central sem texto) + composição programática de layout institucional GOV.MT com `Pillow` (PIL).

- **Provedor de Fallback (Opcional):** **OpenRouter API** (`OPENROUTER_API_KEY`) usando modelos `:free` caso o rate limit da Hugging Face seja atingido, sem simulação de produção; ausência de chave retorna erro explícito.

- **Síntese de Voz / Acessibilidade (RF07):** SAPI5/Microsoft Maria no Windows ou edge-tts opcional, ambos exigindo aprovação persistida do texto exato.

- **Containerização:** `Dockerfile` e `docker-compose.yml` expondo a porta `8000` e incluindo `ffmpeg`.



## 3. Estrutura Obrigatória do Repositório

Respeite estritamente a estrutura exigida pelo edital (adicionando a pasta `web/` dentro de `src/` para o frontend HTML/CSS/JS):



```text

desafio_ia_generativa/

├── README.md

├── AGENTS.md

├── requirements.txt

├── Dockerfile

├── docker-compose.yml

├── .env.example

├── .gitignore

├── config.json

├── dados/

│   ├── originais/        # IMUTÁVEL: casos de texto, áudio, imagem, prompt injection e logo GOV.MT

│   ├── gabaritos/        # Resultados esperados para cálculo de acurácia (RF06, RF08, RF13)

│   └── processados/      # Extrações intermediárias e JSONs estruturados (RF05)

├── src/

│   ├── __init__.py

│   ├── main.py           # Entrypoint: python -m src.main (inicia API/Web UI e CLI de testes)

│   ├── llm_client.py     # Cliente Hugging Face + Fallback OpenRouter + Mock + cálculo de tokens/custo (RF04)

│   ├── prompts.py        # Prompts A, B e C + blindagem XML contra Prompt Injection (RF02, RF03)

│   ├── audio.py          # STT (Whisper HF) e TTS (edge-tts) com filtro de "não localizado" (RF06, RF07)

│   ├── vision.py         # Visão multimodal/OCR (HF VLM) + comparação com gabarito (RF08)

│   ├── image_generation.py # Abordagem Híbrida: Geração HF (FLUX.1) + Moldura Institucional GOV.MT via Pillow (RF10)

│   ├── audit.py          # Logs estruturados, LGPD/minimização e métricas de qualidade (RF11, RF12, RF13)

│   └── web/              # Interface Visual para Revisão Humana (HTML, CSS, JS)

│       ├── index.html

│       ├── styles.css

│       └── app.js

├── prompts/              # Entradas, saídas e matriz comparativa do experimento (Prompts A, B e C)

├── resultados/

│   ├── minutas/

│   ├── audios/

│   ├── imagens/

│   └── logs/

├── testes/               # Testes automatizados com pytest

└── documentacao/         # Relatório técnico, LGPD, custos e registro de uso de IA (Seção 10)

```



## 4. Regras Críticas de Negócio e Segurança (RF01 a RF13)

1. **Imutabilidade:** Nunca altere arquivos dentro de `dados/originais/`.

2. **Segredos e Logs (RF04, RF11):** Jamais exponha `HF_TOKEN` ou `OPENROUTER_API_KEY` nos logs. Trate explicitamente chave ausente, erro 401/403, erro 429 (rate limit), timeout e resposta vazia.

3. **Alucinação Zero e "não localizado" (RF03, RF05, RF09):** Qualquer campo obrigatório ausente deve receber exatamente o valor `"não localizado"`. É proibido inventar prazos, leis, protocolos ou autoridades.

4. **Defesa contra Prompt Injection (RF03):** Envolva todo input externo em tags `<conteudo_nao_confiavel>...</conteudo_nao_confiavel>` instruindo o modelo a tratar comandos internos como mero texto.

5. **Padronização Visual Híbrida GOV.MT (RF10):**

   - O módulo `image_generation.py` deve gerar a ilustração central via IA (`FLUX.1-schnell`) usando prompt estruturado (sujeito, composição, estilo flat institucional nas cores azul `#004A8F`, verde `#008B47` e amarelo `#F7B500` do GOV.MT, iluminação limpa, proporção 1:1 ou 16:9 e restrição explícita de `no text, no words, no letters`).

   - Em seguida, o Python (`Pillow`) deve encaixar essa ilustração dentro do **Template Institucional GOV.MT**, aplicando programaticamente o cabeçalho oficial com a imagem de `dados/originais/gov_mt_logo.png`, o título da orientação em fonte nítida e uma tarja inferior obrigatória de proveniência: `"CONTEÚDO SINTÉTICO GERADO POR IA - Consulte o status de revisão"`, salvando também o JSON de metadados da imagem.

6. **Acessibilidade (RF07):** Antes de sintetizar o áudio da minuta aprovada, substitua ou preceda qualquer ocorrência de `"não localizado"` por um aviso claro ao ouvinte: *"Atenção: informação pendente de localização no sistema"*.

7. **Human-in-the-Loop (RF06, RF08, RF09, RF13):** Nenhuma resposta é finalizada sem aprovação humana na interface HTML/JS (ou CLI). O operador deve poder **Aprovar**, **Editar/Corrigir** ou **Rejeitar/Solicitar Nova Geração**, registrando a justificativa no log de auditoria.



## 5. Comandos de Execução

- **Iniciar Aplicação (Web UI + API):** `python -m src.main` (acessível em `http://localhost:8000`)

- **Executar Pipeline Completo / Experimento via CLI:** `python -m src.main --run-all`

- **Executar via Docker:** `docker compose up --build`

- **Executar Testes Automatizados:** `pytest testes/ -v`
## Integração isolada de 17/10/2026
Preservar motores reais RF06/07/08/10, gabaritos e artefatos.
Mocks somente em testes; modo mock desabilita geração sem conteúdo fictício.
Autenticação ausente: administração RF10 desabilitada até integração do grupo.
Sem mounts públicos /dados ou /resultados. Publicação exige revisão autenticada e SHA-256 atual.
Pillow compõe/corrige; não apresenta desenho determinístico como geração real.
Funcionalidades e pendências atuais: README.md e documentacao/relatorio_tecnico.md.
