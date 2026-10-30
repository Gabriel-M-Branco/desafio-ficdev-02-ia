# Central Inteligente de Atendimento e Consulta Institucional (GOV.MT)

> **Estado atual:** consulte [correções, limites e validação D02](documentacao/CORRECOES_D02.md).
> Execute os testes em cópia descartável com `python -B testes/executar_isolado.py testes/ -v`.
> Para recriar o índice após atualizar o acervo: `python -m src.ingestion` ou módulo 9.

> **Desafios Práticos 01 e 02 — FIC_DEV: Programador de Sistemas com IA (2026)**  
> **Órgão Atendido (Cenário Fictício):** Governo do Estado de Mato Grosso — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT) e Escola Técnica Estadual de Cuiabá (ETEC).

---

Membros do trio: Gabriel Moreira Branco, Emilly Caroline dos Santos Arruda e Marcos Vinícius G. S. Campos.

## 1. Visão Geral da Solução

Este projeto implementa uma solução multimodal completa de apoio ao atendimento ao cidadão, consulta normativa com **RAG (Retrieval-Augmented Generation)** e comunicação oficial, desenvolvida em estrita conformidade com as diretrizes dos editais dos **Desafios Práticos 01 (`RF01` a `RF13`)** e **02 (`RF14` a `RF24`)** e os padrões visuais e institucionais do **Governo do Estado de Mato Grosso (GOV.MT)**.

A **única interface oficial consolidada** do sistema é construída em **Streamlit (`src/app.py`)**, centralizando:
1. Recepção e triagem multimodal (**Texto**, **Áudio STT** e **Imagem/PDF com OCR**);
2. Extração estruturada validada por esquemas **Pydantic v2 (`extra="forbid"`)**, separando explicitamente **extração literal** e **informação inferida**;
3. **Assistente de Documentos Institucionais (RAG)** fundamentado em editais e retificações, com citações explícitas (documento, versão, página/seção, `trecho_id`), abstenção segura sem evidência e detecção de conflitos entre normas;
4. **Atendimento Integrado com Minuta Fundamentada**, separando fatos informados pelo solicitante e orientações sustentadas pelo acervo;
5. **Painel Analítico de Sentimentos** com classificação em 4 polaridades e agregação determinística em Python;
6. **Governança do Acervo, Auditoria, LGPD e Revisão Humana (*Human-in-the-Loop*)** obrigatória antes de qualquer publicação ou síntese final de voz;
7. **Central de Execução e Verificação de Testes (Módulo 10)** com disparo ao vivo da bateria contratual (T01 a T15), asserções individuais sob demanda e terminal interativo do pytest.

---

## 2. Stack Tecnológica e Provedores Configuráveis

- **Linguagem & Interface Oficial:** Python 3.11+ / **Streamlit (`src/app.py`)** + serviços internos FastAPI (`src/main.py`)
- **Provedores de Inteligência Artificial Configuráveis (`RF04`, `RF21`):**
  - **OpenAI API (`OPENAI_API_KEY`, `TEXT_PROVIDER=openai`):** Suporte nativo a `gpt-4o-mini` (ou modelo configurável via `OPENAI_MODEL`).
  - **OpenRouter API (`OPENROUTER_API_KEY`, `TEXT_PROVIDER=openrouter`):** Suporte a `openrouter/free`, `google/gemini-3.8-flash` e `meta-llama/Llama-3.3-70B-Instruct:free`.
  - **Hugging Face Serverless Inference API (`HF_TOKEN`, `TEXT_PROVIDER=huggingface`):** Suporte a `Qwen/Qwen2.5-72B-Instruct`, `FLUX.1-schnell` e `whisper-large-v3-turbo`.
  - **Adaptador Simulado Identificado (`TEXT_PROVIDER=adaptador_simulado`):** Segunda configuração de geração compatível para demonstração e testes de arquitetura (`RF21` / `T12`) sem reconstruir o índice vetorial.
- **Processamento Multimodal & RAG:**
  - **Ingestão e OCR:** `PyMuPDF` (`fitz`) + `Tesseract OCR` local em português (`por.traineddata`)
  - **Áudio STT e TTS:** `faster-whisper` / Whisper HF e `edge-tts` / `SAPI5 (Microsoft Maria)` com aviso sonoro obrigatório para campos `"não localizado"`
  - **Busca Vetorial Persistente:** `scikit-learn` (`TfidfVectorizer` + `cosine_similarity`) + `numpy` persistido em `indice/indice_vetorial.json`
  - **Validação de Contratos:** `Pydantic v2` (`src/schemas.py`)

---

## 3. Estrutura do Repositório

```text
desafio-ficdev-02-ia/
├── README.md                 # Guia completo de instalação, execução e arquitetura
├── AGENTS.md                 # Diretrizes arquiteturais e regras do agente (RF01 a RF24)
├── requirements.txt          # Dependências do projeto
├── pytest.ini                # Configuração do ambiente de testes
├── Dockerfile                # Imagem Docker com Python 3.11, ffmpeg e Streamlit (8501)
├── docker-compose.yml        # Orquestração do container
├── .env.example              # Exemplo de variáveis de ambiente sem segredos
├── config.json               # Caminhos, modelos, parâmetros RAG/chunking (v2.0.0)
├── dados/
│   ├── originais/            # IMUTÁVEL: casos de texto, áudio, imagem, editais e brasão GOV.MT
│   ├── acervo/               # 6 documentos institucionais fictícios (3 .txt + 3 .pdf) para RAG
│   ├── solicitacoes/         # 6 solicitações fictícias (4 completas, 1 incompleta, 1 ambígua)
│   ├── avaliacoes/           # 12 avaliações de atendimento (3 pos, 3 neg, 3 neu, 3 indet)
│   ├── gabaritos/            # Gabaritos oficiais para avaliação automatizada (D01 e D02)
│   └── processados/          # Extrações estruturadas intermediárias e fichas processadas
├── indice/
│   └── indice_vetorial.json  # Índice vetorial persistente com metadados, hashes e versão
├── src/
│   ├── app.py                # INTERFACE OFICIAL UNIFICADA EM STREAMLIT (Módulos 1 a 10)
│   ├── main.py               # Entrypoint complementar (Streamlit padrão, --api, --cli, --run-all)
│   ├── llm_client.py         # Cliente multi-provedor (OpenAI, OpenRouter, HF, Adaptador Simulado)
│   ├── schemas.py            # Contratos Pydantic v2 (extra="forbid"), literal vs inferido (RF14/RF15)
│   ├── nlp.py                # Sumarização <= 100 palavras, NER, categorização e retry (RF14/RF15)
│   ├── guardrails.py         # Guardrails de entrada/arquivo/corpus/saída e limites (RF16)
│   ├── ingestion.py          # Leitura .txt/.pdf e chunking comparativo Config A vs Config B (RF18)
│   ├── embeddings.py         # Índice vetorial persistente, deduplicação e exclusão (RF17/RF24)
│   ├── rag.py                # Motor RAG fundamentado, conflitos e minuta fundamentada (RF19/RF20)
│   ├── sentiment.py          # Sentimentos com prompt isolado e agregação determinística (RF22)
│   ├── metrics.py            # Avaliador automatizado da matriz T01 a T15 (RF18/RF23)
│   ├── prompts.py            # Prompts A, B, C e blindagem XML anti-injection (RF02/RF03)
│   ├── audio.py              # STT e TTS com exigência de aprovação humana (RF06/RF07)
│   ├── vision.py             # Visão computacional / OCR e comparação de gabarito (RF08)
│   ├── image_generation.py   # Peça visual híbrida (IA + Pillow GOV.MT) (RF10)
│   ├── image_access.py       # Controle de revisão e publicação por SHA-256 (RF10)
│   ├── pdf_generator.py      # Geração de documento PDF oficial timbrado GOV.MT (RF09)
│   └── audit.py              # Auditoria estruturada, mascaramento PII/segredos e LGPD (RF11-RF13/RF21)
├── prompts/                  # Saídas dos Prompts A, B, C e matriz comparativa
├── resultados/
│   ├── minutas/              # Minutas geradas (.txt e .pdf)
│   ├── audios/               # Áudios sintetizados para acessibilidade (.mp3 / .wav)
│   ├── imagens/              # Comunicados oficiais gerados (.png e .json)
│   ├── logs/                 # Trilha de auditoria estruturada (JSON e JSONL)
│   └── metricas/             # Relatório consolidado da matriz T01 a T15 (relatorio_avaliacao_d02.json)
├── testes/                   # Suíte de testes automatizados com pytest (316+ testes)
└── documentacao/             # Relatório técnico, Matriz de Rastreabilidade, LGPD e registro de IA
```

---

## 4. Instalação e Configuração

### Passo 1: Criar e Ativar o Ambiente Virtual (`.venv`)

#### No Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### No Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Passo 2: Configurar Variáveis de Ambiente (`.env`)

```powershell
Copy-Item .env.example .env
```

Edite `.env` conforme o provedor desejado:
```env
TEXT_PROVIDER=openai
OPENAI_API_KEY=sua_chave_openai_aqui
OPENAI_MODEL=gpt-4o-mini
OPENROUTER_API_KEY=sua_chave_openrouter_opcional
HF_TOKEN=seu_token_huggingface_opcional
EXECUTION_MODE=auto
PORT=8501
```

---

## 5. Comandos de Execução

### 5.1. Interface Oficial Unificada em Streamlit (`RF20`)

```bash
streamlit run src/app.py
```
ou diretamente pelo entrypoint principal:
```bash
python -m src.main
```
Acesse no navegador: **`http://localhost:8501`**

### 5.2. Matriz de Avaliação Automatizada do Desafio 02 (`T01` a `T15` — `RF23`)

```bash
python -m src.metrics
```
Gera o relatório completo em `resultados/metricas/relatorio_avaliacao_d02.json` e `dados/processados/solicitacoes_d02_processadas.json`.

### 5.3. Suíte Completa de Testes Automatizados (`pytest`)

```bash
pytest testes/ -v
```

### 5.4. Execução via Docker

```bash
docker compose up --build
```
Acesse em: **`http://localhost:8501`**

---

## 6. Documentação e Entregáveis

- [Matriz de Rastreabilidade Completa (RF01 a RF24 e T01 a T15)](documentacao/MATRIZ_RASTREABILIDADE.md)
- [Relatório Técnico Arquitetural, RAG, Chunking e Custos](documentacao/relatorio_tecnico.md)
- [Registro de Uso de Inteligência Artificial](documentacao/registro_uso_ia.md)
- [Matriz Comparativa do Experimento de Prompts](prompts/matriz_comparativa.md)
- [Diretrizes de Arquitetura e Regras do Agente](AGENTS.md)
