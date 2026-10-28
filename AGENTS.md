# AGENTS.md - Diretrizes Arquiteturais, Segurança e Regras do Agente (RF01 a RF24)

## 1. Visão Geral e Escopo do Projeto

Protótipo da **Central Inteligente de Atendimento, Consulta Documental (RAG) e Comunicação Institucional** compatível com os padrões visuais e normativos do **GOV.MT / SECITECI-MT**, contemplando integralmente:

- **Desafio Prático 01 (`RF01` a `RF13`):** Processamento multimodal de solicitações (texto, áudio STT e imagem/PDF via OCR), extração estruturada JSON, experimentos de prompts (`A`, `B` e `C`), geração de minutas institucionais, síntese de voz acessível (TTS), geração híbrida de peças visuais (`FLUX` + moldura programática `Pillow` `GOV.MT`), *Human-in-the-loop* e trilha de auditoria/LGPD.
- **Desafio Prático 02 (`RF14` a `RF24`):** Validação estrita por esquema (`Pydantic`) com regras de negócio e coerência factual, resumo/classificação/extração de entidades de solicitações, *guardrails* de entrada/contexto/saída, ingestão documental (`.txt` e `.pdf`), experimentos de *chunking* (`Config A: 400/80` vs. `Config B: 800/150`), indexação e busca vetorial persistida, assistente RAG com citações/abstenção/detecção de conflitos e geração de minutas fundamentadas, abstração de provedor sem reconstrução de índice, análise determinística e assistida de sentimento, suíte de avaliação (`T01` a `T15`) e matriz de rastreabilidade.

---

## 2. Decisão Arquitetural e Stack Tecnológica

- **Interface Oficial Única:** **Streamlit (`src/app.py`)** é a única interface gráfica oficial do projeto (`RF20`). O antigo frontend em HTML/CSS/JS (`src/web/`) foi descontinuado para centralizar toda a operação, consulta RAG, revisão humana (*Human-in-the-loop*) e painéis de métricas/sentimento no Streamlit.
- **Linguagem & Ponto de Entrada:** Python 3.11+ acionado via `streamlit run src/app.py` ou `python -m src.main` (que inicia o Streamlit por padrão ou executa os modos de linha de comando `--cli` / `--run-all`).
- **Provedores de Geração Configuráveis (`RF01`, `RF04`, `RF21`):**
  - **OpenAI API (`OPENAI_API_KEY`):** Suporte nativo via endpoint compatível (`gpt-4o-mini` / configurável em `config.json` ou variável de ambiente).
  - **Hugging Face Serverless Inference API (`HF_TOKEN`):** `Qwen/Qwen2.5-72B-Instruct` ou `meta-llama/Llama-3.3-70B-Instruct`.
  - **OpenRouter API (`OPENROUTER_API_KEY`):** Provedor adicional / *fallback* configurável.
  - **Adaptador Local / Simulado Identificado (`RF21`):** Usado para validação local reprodutível e demonstração de segunda configuração de geração (`T12`), sempre identificado explicitamente nos metadados e logs (`modo_execucao`), sem jamais fingir chamada remota real. A troca do provedor de geração **nunca reconstrói o índice vetorial**.
- **Motores Multimodais Reais Preservados (`RF06`, `RF07`, `RF08`, `RF10`):**
  - **Áudio STT (`RF06`):** `faster-whisper` local (`small`/`CPU`/`int8`/`pt`) ou Whisper via API configurável.
  - **Áudio TTS (`RF07`):** `SAPI5` (Windows) ou `edge-tts`, exigindo aprovação humana persistida do texto exato antes da síntese e convertendo `"não localizado"` em aviso auditivo claro.
  - **Visão/OCR (`RF08`):** `PyMuPDF` + `Tesseract` (`por`) local com comparação contra gabarito.
  - **Imagem Híbrida (`RF10`):** Ilustração central sem texto via IA (`Cloudflare Workers AI FLUX` / `HF FLUX.1-schnell`) + composição programática do template institucional `GOV.MT` via `Pillow`, com controle de publicação vinculado a revisão autenticada e hash `SHA-256`.

---

## 3. Estrutura Obrigatória do Repositório

```text
desafio-ficdev-02-ia/
├── README.md
├── AGENTS.md
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── config.json
├── dados/
│   ├── originais/        # IMUTÁVEL: casos D01 (texto, áudio, imagem, injection, logo) e editais/
│   ├── acervo/           # 6 documentos institucionais fictícios (DOC-SECITECI-001 a 006 em .txt/.pdf)
│   ├── solicitacoes/     # 6 solicitações fictícias (4 completas, 1 incompleta, 1 ambígua)
│   ├── avaliacoes/       # 12 avaliações de atendimento (positivas, negativas, neutras, ambíguas)
│   ├── gabaritos/        # Gabaritos oficiais D01 e D02 (texto, áudio, visão, solicitações, RAG, sentimento, adversarial)
│   └── processados/      # Extrações intermediárias e JSONs estruturados validados (RF05, RF14, RF15)
├── indice/
│   └── indice_vetorial.json # Índice vetorial persistido em disco com metadados (RF17, RF18)
├── src/
│   ├── __init__.py
│   ├── app.py            # Interface Oficial Única em Streamlit (RF01 a RF24)
│   ├── main.py           # Entrypoint CLI (--cli, --run-all) e inicializador do Streamlit
│   ├── llm_client.py     # Cliente multi-provedor (OpenAI, HF, OpenRouter, Adaptador Identificado) (RF01, RF04, RF21)
│   ├── prompts.py        # Prompts A, B e C + blindagem XML contra Prompt Injection (RF02, RF03)
│   ├── text_contract.py  # Contratos de validação textual e minutas do Desafio 01 (RF03, RF05, RF09)
│   ├── schemas.py        # Esquemas Pydantic, regras de negócio e coerência com o original (RF14)
│   ├── nlp.py            # Resumo, classificação, extração literal vs. inferida e ficha estruturada (RF14, RF15)
│   ├── guardrails.py     # Guardrails de arquivo, tamanho, escopo, injection direta/indireta e limite de chamadas (RF16)
│   ├── ingestion.py      # Leitura .txt/.pdf, limpeza e chunking configurável (Config A e B) (RF17, RF18)
│   ├── embeddings.py     # Vetorização determinística, persistência, deduplicação e exclusão por id_documento (RF17, RF18)
│   ├── rag.py            # Motor RAG fundamentado, citações, abstenção, conflitos e minutas fundamentadas (RF19, RF20)
│   ├── sentiment.py      # Classificação de sentimento (regras + prompt isolado) e agregação determinística (RF22)
│   ├── metrics.py        # Avaliador automatizado da matriz T01 a T15 e geração de relatórios (RF23)
│   ├── audio.py          # STT e TTS acessível com trava de aprovação humana (RF06, RF07)
│   ├── vision.py         # OCR multimodal e avaliação contra gabarito (RF08)
│   ├── image_generation.py # Geração híbrida de imagem GOV.MT + Pillow (RF10)
│   ├── image_access.py   # Controle de acesso e verificação SHA-256 para publicação de imagens (RF10)
│   ├── pdf_generator.py  # Exportação de minutas institucionais em PDF
│   └── audit.py          # Trilha de auditoria JSONL/JSON, mascaramento LGPD e métricas (RF11, RF12, RF13, RF21)
├── prompts/              # Entradas, saídas e matriz comparativa do experimento (Prompts A, B e C)
├── resultados/
│   ├── minutas/
│   ├── audios/
│   ├── imagens/
│   ├── logs/             # audit_trail.jsonl e EXEC_*.json com mascaramento de segredos e PII
│   └── metricas/         # Relatórios consolidados da avaliação D02 e matriz T01 a T15 (RF23)
├── testes/               # Suíte automatizada pytest (D01 + D02: T01 a T15)
└── documentacao/         # Relatório técnico, registro de uso de IA e MATRIZ_RASTREABILIDADE.md (RF24)
```

---

## 4. Regras Críticas de Negócio, Segurança e Qualidade (`RF01` a `RF24`)

1. **Imutabilidade das Fontes Originais:** Nunca altere, mova ou sobrescreva arquivos dentro de `dados/originais/` (incluindo `dados/originais/editais/`).
2. **Proteção de Segredos e Dados Pessoais (`RF04`, `RF11`, `RF12`, `RF21`):**
   - Jamais exponha `OPENAI_API_KEY`, `HF_TOKEN` ou `OPENROUTER_API_KEY` em código, respostas, interface ou logs.
   - Nos logs (`resultados/logs/`), mascare chaves de API (sem mascarar métricas numéricas como `max_tokens`, `prompt_tokens` ou `total_tokens`) e aplique mascaramento de identificadores pessoais (`CPF`, `e-mail`) tanto no `audit_trail.jsonl` quanto nos arquivos `EXEC_*.json`.
3. **Alucinação Zero, Coerência com o Original e `"não localizado"` (`RF03`, `RF05`, `RF09`, `RF14`, `RF15`):**
   - Campos obrigatórios ausentes no Desafio 01 recebem `"não localizado"`; nos esquemas `Pydantic` do Desafio 02 (`ExtracaoFicha`), campos ausentes são listados em `campos_ausentes` e valores ausentes permanecem `None`.
   - Toda entidade extraída deve ser verificada quanto à coerência com o `texto_original` (`T02`), separando extração literal de informação inferida (`RF15`).
4. **Defesa em Camadas e Guardrails (`RF03`, `RF16`, `T04`, `T05`):**
   - Valide tipo e tamanho de arquivo, comprimento máximo da entrada, aderência ao escopo institucional (`SECITECI-MT`) e limite máximo de chamadas por execução (`MAX_CHAMADAS_POR_EXECUCAO`).
   - Envolva entradas do usuário em `<conteudo_nao_confiavel>...</conteudo_nao_confiavel>` e trechos recuperados do acervo em `<documento_recuperado>...</documento_recuperado>`, sanitizando instruções maliciosas tanto na solicitação (`ADV-01`) quanto no corpus (`ADV-02`) e bloqueando exfiltração de segredos (`ADV-03`).
5. **Fundamentação Documental, Abstenção e Conflitos no RAG (`RF17`, `RF18`, `RF19`, `RF20`):**
   - Toda resposta ou minuta gerada pelo RAG deve citar `id_documento`, `titulo`, `versao` e `trecho` recuperado.
   - Se a evidência for insuficiente (`P6`, `P7`), o sistema deve **abster-se explicitamente** (`status_decisao="abstencao"`), declarar o que falta e recomendar encaminhamento humano.
   - Se houver divergência normativa entre documentos/versões (`P8`: `DOC-SECITECI-004` vs. `DOC-SECITECI-006`), o sistema deve **sinalizar o conflito** (`status_decisao="conflito"`), citar ambos os documentos e recomendar validação humana (`necessita_revisao_humana=True`).
   - A geração de minuta fundamentada (`RF19`) deve separar explicitamente os **fatos informados pelo cidadão** e as **orientações extraídas do acervo**.
6. **Preservação dos Motores Reais e Revisão Humana (`RF06`, `RF07`, `RF08`, `RF09`, `RF10`, `RF20`):**
   - Nenhuma minuta é dada como finalizada sem decisão humana (`pendente`, `aprovada`, `rejeitada`, `revisar`).
   - A síntese de voz (`RF07`) exige aprovação humana persistida do texto exato (`exigir_aprovacao=True`) e substitui `"não localizado"` por *"Atenção: informação pendente de localização no sistema"*.
   - A publicação de imagem (`RF10`) exige revisão autenticada e verificação de hash `SHA-256` atual.
7. **Verificação Obrigatória Antes de Concluir Tarefas (`RF23`, `RF24`):**
   - Nunca confie cegamente em artefatos pré-existentes. Sempre execute `pytest testes/ -v` e valide a matriz `T01` a `T15` antes de declarar qualquer etapa concluída.

---

## 5. Comandos Oficiais de Execução, Indexação e Testes

- **Iniciar Interface Oficial (Streamlit):**
  ```bash
  streamlit run src/app.py
  # ou
  python -m src.main
  ```
- **Executar Pipeline Completo do Desafio 01 via CLI:**
  ```bash
  python -m src.main --run-all
  ```
- **Executar Avaliação Completa do Desafio 02 (Matriz `T01` a `T15` e Relatório de Métricas):**
  ```bash
  python -m src.metrics
  ```
- **Executar Suíte Completa de Testes Automatizados (Regressão D01 + D02):**
  ```bash
  pytest testes/ -v
  ```
- **Executar via Docker:**
  ```bash
  docker compose up --build
  ```
