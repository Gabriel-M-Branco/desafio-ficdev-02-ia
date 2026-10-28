# Central Inteligente de Atendimento e Comunicação Institucional (GOV.MT)

> **Desafio Prático 1 — FIC_DEV: Programador de Sistemas com IA (2026)**  
> **Órgão Atendido (Cenário Fictício):** Governo do Estado de Mato Grosso — Secretaria de Estado de Ciência, Tecnologia e Inovação (SECITECI/MT) e Escola Técnica Estadual de Cuiabá (ETEC).

---

Membros do trio: Gabriel Moreira Branco, Emilly Caroline dos Santos Arruda e Marcos Vinícius G. S. Campos.

## 1. Visão Geral da Solução

Este projeto implementa uma solução multimodal completa de apoio ao atendimento ao cidadão e comunicação oficial, desenvolvida em estrita conformidade com as diretrizes do edital (Requisitos **RF01** a **RF13**) e os padrões visuais e institucionais do **Governo do Estado de Mato Grosso (GOV.MT)**.

O sistema recebe solicitações fictícias em múltiplos formatos (**Texto**, **Áudio** e **Imagem/Documento Digitalizado**), extrai dados estruturados em JSON, redige minutas institucionais seguras com base estrita no princípio de **Alucinação Zero**, produz recurso falado para acessibilidade com sintetização neural e gera comunicados visuais padronizados com identificação de conteúdo sintético.

### Princípios de Segurança e Governança
- **Nenhum Envio Automático:** Toda minuta de resposta depende compulsoriamente de validação, ajuste ou rejeição justificada por um servidor humano (*Human-in-the-Loop*).
- **Alucinação Zero e "não localizado":** É estritamente vedada a invenção de leis, decretos, protocolos ou prazos. Qualquer informação omitida recebe compulsoriamente o valor literal `"não localizado"`.
- **Blindagem contra Prompt Injection:** Entradas externas são isoladas dentro de tags delimitadoras `<conteudo_nao_confiavel>`, instruindo o modelo a tratar comandos inseridos como dados textuais inertes.
- **Rastreabilidade e Proteção de Segredos:** Trilha de auditoria integral sem exposição de chaves de API nos logs ou no repositório.

---

## 2. Stack Tecnológica

- **Linguagem & Backend:** Python 3.11+ / FastAPI / Uvicorn
- **Interface Humana (Web UI):** HTML5, CSS3 e JavaScript Vanilla (Design institucional com as cores oficiais `#004A8F`, `#008B47` e `#F7B500`)
- **Provedores de Inteligência Artificial Configuráveis:**
  - **OpenRouter API (`OPENROUTER_API_KEY`):** Suporte nativo aos modelos de última geração:
    - **VLM (OCR Multimodal de Alta Precisão):** `google/gemini-3.8-flash` (com fallback automático e transparente para Tesseract local)
    - **LLM (Extração e Minuta):** `google/gemini-3.8-flash` ou `Qwen/Qwen2.5-72B-Instruct`
    - **Áudio STT:** `google/gemini-3.8-flash` ou Whisper local (`faster-whisper`)
    - **TTS Neural de Acessibilidade:** `google/gemini-3.8-flash-tts` com fallback para `edge-tts` e `SAPI5 (Microsoft Maria)`
    - **Imagem Institucional:** `google/gemini-3.1-flash-image` ou Cloudflare / FLUX.1 + Pillow GOV.MT
  - **Hugging Face Serverless Inference API (`HF_TOKEN`):** Suporte a `Qwen/Qwen2.5-72B-Instruct`, `Qwen/Qwen2.5-VL-7B-Instruct`, `FLUX.1-schnell` e `whisper-large-v3-turbo`
  - **Processamento Local & Resiliência:** PyMuPDF, Tesseract OCR em português (`por.traineddata`), SAPI5 e modo offline a custo financeiro zero.
- **Containerização:** Docker e Docker Compose com suporte a `ffmpeg` e OCR.

---

## 3. Estrutura do Repositório

```text
desafio-01-ia-ficdev/
├── README.md                 # Guia completo de instalação e uso
├── AGENTS.md                 # Diretrizes arquiteturais e regras do agente
├── requirements.txt          # Dependências do projeto
├── pytest.ini                # Configuração do ambiente de testes
├── Dockerfile                # Imagem Docker com Python 3.11 e ffmpeg
├── docker-compose.yml        # Orquestração do container
├── .env.example              # Exemplo de variáveis de ambiente sem segredos
├── .gitignore                # Regras de exclusão de arquivos sensíveis e temporários
├── config.json               # Caminhos, modelos e parâmetros não-sensíveis
├── dados/
│   ├── originais/            # IMUTÁVEL: arquivos de entrada e brasão oficial GOV.MT
│   ├── gabaritos/            # Resultados esperados para avaliação de acurácia
│   └── processados/          # Extrações estruturadas intermediárias (JSON)
├── src/
│   ├── __init__.py
│   ├── main.py               # Ponto de entrada oficial (API Web e CLI)
│   ├── llm_client.py         # Cliente OpenRouter / HF / Mock com cálculo de custos
│   ├── prompts.py            # Prompts A, B, C e blindagem XML anti-injection
│   ├── audio.py              # STT (Whisper/Gemini) e TTS com aviso auditivo de ausências
│   ├── vision.py             # Visão computacional / OCR e comparação de gabarito
│   ├── image_generation.py   # Peça visual híbrida (IA + Pillow GOV.MT)
│   ├── pdf_generator.py      # Geração de documento PDF oficial timbrado GOV.MT
│   ├── audit.py              # Auditoria, LGPD e avaliação de qualidade
│   └── web/                  # Interface Web para Human-in-the-Loop
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── prompts/                  # Saídas dos Prompts A, B, C e matriz comparativa
├── resultados/
│   ├── minutas/              # Minutas geradas (.txt e .pdf)
│   ├── audios/               # Áudios sintetizados para acessibilidade (.mp3)
│   ├── imagens/              # Comunicados oficiais gerados (.png e .json)
│   └── logs/                 # Trilha de auditoria estruturada (JSON e JSONL)
├── testes/                   # Suíte de testes automatizados com pytest
└── documentacao/             # Relatório técnico, LGPD e registro de uso de IA
```

---

## 4. Instalação e Configuração (Passo a Passo)

O sistema foi concebido para execução totalmente agnóstica de sistema operacional, resolvendo todos os diretórios e caminhos de forma dinâmica e relativa à raiz do projeto.

### Pré-requisitos
- Python 3.11 ou superior instalado
- Git instalado
- (Opcional) Docker e Docker Compose

---

### Passo 1: Clonar o Repositório

```bash
git clone https://github.com/Gabriel-M-Branco/desafio-01-ia-ficdev.git
cd desafio-01-ia-ficdev
```

---

### Passo 2: Criar e Ativar o Ambiente Virtual (`.venv`)

Selecione a instrução correspondente ao seu sistema operacional:

#### No Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*(Caso haja restrição de execução de scripts no PowerShell, execute antes: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

#### No Windows (Prompt de Comando - CMD):
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

#### No Linux (Bash):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### No macOS (Zsh / Terminal):
```zsh
python3 -m venv .venv
source .venv/bin/activate
```

---

### Passo 3: Instalar as Dependências

Com o ambiente virtual ativado:

#### Windows (PowerShell ou CMD):
```cmd
pip install -r requirements.txt
```

#### Linux e macOS:
```bash
pip install -r requirements.txt
```

---

### Passo 4: Configurar Variáveis de Ambiente (`.env`)

Crie o arquivo `.env` a partir do modelo de exemplo:

#### No Windows (PowerShell):
```powershell
Copy-Item .env.example .env
```

#### No Windows (Prompt de Comando - CMD):
```cmd
copy .env.example .env
```

#### No Linux e macOS:
```bash
cp .env.example .env
```

Edite o arquivo `.env` gerado para inserir suas credenciais:
```env
OPENROUTER_API_KEY=sua_chave_openrouter_aqui
HF_TOKEN=seu_token_huggingface_opcional
EXECUTION_MODE=auto
PORT=8000
```
> **Nota de Resiliência:** Caso nenhuma chave seja inserida no `.env`, o sistema executará com seu **Modo de Contingência Local**, garantindo a operação integral da interface web, das minutas e da suíte de testes com dados fiéis ao edital e custo financeiro estritamente zero.

---

## 5. Instruções de Execução por Sistema Operacional

Todas as modalidades podem ser acionadas em qualquer plataforma:

### 5.1. Interface Web Oficial (FastAPI + Painel Human-in-the-Loop)

Inicia o servidor com a interface web institucional na porta `8000`:

- **Windows (PowerShell ou CMD):**
  ```cmd
  python -m src.main
  ```
- **Linux e macOS:**
  ```bash
  python3 -m src.main
  ```

Acesse no navegador: **`http://localhost:8000`**

Recursos disponíveis na interface web:
- Triagem e processamento em tempo real de texto, áudio e imagem digitalizada.
- Visualização de extração estruturada em JSON e edição formal da minuta de despacho.
- Exportação da minuta deliberada em **documento PDF timbrado oficial do GOV.MT** com brasão institucional.
- Síntese sonora da resposta via TTS neural com aviso auditivo de campos pendentes de localização.
- Deliberação formal pelo servidor responsável (*Aprovar*, *Corrigir* ou *Rejeitar* com justificativa).
- Geração da peça visual híbrida padronizada com Brasão Oficial e tarja de proveniência de IA.
- Acompanhamento da trilha de auditoria e da matriz de conformidade LGPD.

---

### 5.2. Interface Unificada em Streamlit (Migração Completa dos Desafios 01 e 02)

Inicia a interface unificada completa em Streamlit na porta `8501`, reunindo a Central de Atendimento ao Cidadão, Experimento de Prompts, Áudio/OCR Multimodal, Imagem Institucional, Auditoria/LGPD, Assistente de Documentos RAG, Ficha Estruturada, Painel de Sentimentos e Governança do Acervo:

- **Windows (PowerShell ou CMD):**
  ```cmd
  streamlit run src/app.py
  ```
- **Linux e macOS:**
  ```bash
  streamlit run src/app.py
  ```

Acesse no navegador: **`http://localhost:8501`**


---

### 5.3. Execução Completa Automatizada (`--run-all`)

Executa o pipeline institucional de ponta a ponta, processa todas as modalidades, efetua a validação contra gabaritos e salva todos os artefatos nos diretórios relativos (`dados/processados/`, `resultados/` e `prompts/`):

- **Windows (PowerShell ou CMD):**
  ```cmd
  python -m src.main --run-all
  ```
- **Linux e macOS:**
  ```bash
  python3 -m src.main --run-all
  ```

---

### 5.4. Modo Linha de Comando Interativo (`--cli`)

Para operadores que optarem por interagir via terminal institucional:

- **Windows (PowerShell ou CMD):**
  ```cmd
  python -m src.main --cli
  ```
- **Linux e macOS:**
  ```bash
  python3 -m src.main --cli
  ```

---

### 5.5. Execução Multiplataforma via Docker

Caso prefira executar em container isolado com `ffmpeg` e todas as dependências pré-configuradas (funciona de forma idêntica em Windows, Linux e macOS):

```bash
docker compose up --build
```
Acesse em: `http://localhost:8000`

---

## 6. Testes Automatizados

A suíte cobre 100% dos requisitos funcionais (**RF01 a RF13**), incluindo avaliação de gabarito, segurança de segredos e geração de PDF timbrado:

- **Windows (PowerShell ou CMD):**
  ```cmd
  pytest testes/ -v
  ```
- **Linux e macOS:**
  ```bash
  pytest testes/ -v
  ```

---

## 7. Mapeamento dos Requisitos Funcionais (RF01 a RF13)

| Requisito | Descrição | Onde está implementado |
|---|---|---|
| **RF01** | Inicialização, configuração e segredos | `src/main.py`, `config.json`, `.env.example` |
| **RF02** | Experimento de engenharia de prompts (A, B e C) | `src/prompts.py`, `prompts/matriz_comparativa.md` |
| **RF03** | Prompt seguro, "não localizado" e anti-injection | `src/prompts.py` (Classe `SegurancaPrompts`) |
| **RF04** | Chamada de API, fallback, métricas e custo zero | `src/llm_client.py` |
| **RF05** | Entrada textual e extração estruturada (JSON) | `src/main.py`, `dados/processados/` |
| **RF06** | Transcrição de áudio (STT) e conferência de gabarito | `src/audio.py`, `dados/gabaritos/gabarito_audio.json` |
| **RF07** | Síntese de voz e acessibilidade (TTS) com alerta de ausências e fallback local SAPI5 | `src/audio.py` (OpenRouter / edge-tts / SAPI5), `resultados/audios/` |
| **RF08** | Visão computacional, OCR e justificativa de soberania | `src/vision.py` (OpenRouter VLM / Tesseract), `dados/gabaritos/gabarito_visao.json` |
| **RF09** | Geração de minuta institucional sem alucinação e exportação em PDF timbrado | `src/main.py`, `src/pdf_generator.py`, `resultados/minutas/` |
| **RF10** | Geração de peça visual GOV.MT, suporte Cloudflare AI e moderação HITL | `src/image_generation.py`, `src/image_access.py`, `resultados/imagens/` |
| **RF11** | Registro de auditoria estruturada e rastreabilidade | `src/audit.py` (AuditLogger), `resultados/logs/` |
| **RF12** | LGPD, privacidade, minimização e mascaramento | `src/audit.py` (LGPDManager), `documentacao/` |
| **RF13** | Avaliação de qualidade e revisão humana (HITL) | `src/audit.py` (QualityEvaluator), Interface Web |

---

## 8. Limitações Conhecidas e Trabalhos Futuros

1. **Dependência de Conectividade Externa nas APIs Serverless:** Embora o sistema conte com fallback mock local e Tesseract OCR, chamadas à API da Hugging Face e OpenRouter estão sujeitas à latência de rede e filas momentâneas do tier gratuito. Em implantação de produção definitiva, recomenda-se hospedar modelos locais (ex: `Qwen2.5-7B` via Ollama/vLLM on-premise) para garantir soberania de dados.
2. **Documentos Manuscritos Complexos:** A precisão de extração de campos manuscritos em formulários de baixa resolução depende da legibilidade da caligrafia do cidadão, tornando indispensável a etapa de confirmação humana do servidor público implementada na interface.
3. **Evolução de Acessibilidade:** Em versões futuras, prevê-se a inclusão de avatar institucional com tradução em Libras (Língua Brasileira de Sinais) para além do suporte auditivo.

---

## 9. Documentação e Entregáveis

- [Relatório Técnico Arquitetural e Custos](documentacao/relatorio_tecnico.md)
- [Registro de Uso de Inteligência Artificial](documentacao/registro_uso_ia.md)
- [Matriz Comparativa do Experimento de Prompts](prompts/matriz_comparativa.md)
- [Diretrizes de Arquitetura e Regras de Negócio](AGENTS.md)

---

## 10. Evolução do Protótipo — Desafio Prático 02 (RF14 a RF24)

O Desafio 02 expande a central multimodal adicionando consulta a acervo institucional fictício, busca vetorial persistente, geração fundamentada com RAG, guardrails em camadas, classificação de sentimentos e uma interface em **Streamlit** para o assistente de documentos.

### 10.1. Como Executar a Interface Streamlit (RF20)

Para iniciar o Assistente de Documentos, RAG e Painel de Sentimentos:

```bash
streamlit run src/app.py
```
Acesse em: `http://localhost:8501`

### 10.2. Mapeamento dos Novos Requisitos (RF14 a RF24)

| Requisito | Funcionalidade | Módulo Responsável |
|---|---|---|
| **RF14** | Contratos de dados Pydantic v2, ausências com `null` e regras de negócio | `src/schemas.py` |
| **RF15** | Sumarização <= 100 palavras, NER literal e categorização | `src/nlp.py` |
| **RF16** | Guardrails, moderação de escopo, bloqueio de injeção e limites | `src/guardrails.py` |
| **RF17** | Embeddings e índice vetorial persistente com deduplicação | `src/embeddings.py` |
| **RF18** | Chunking comparativo e acerto de recuperação top-k | `src/ingestion.py` |
| **RF19** | RAG fundamentado com fontes, abstenção e detecção de conflitos | `src/rag.py` |
| **RF20** | Assistente de documentos e revisão humana em Streamlit | `src/app.py` |
| **RF21** | Provedor configurável e trilha de auditoria sem segredos | `src/llm_client.py`, `src/audit.py` |
| **RF22** | Classificação de 12 sentimentos e agregação determinística via código | `src/sentiment.py` |
| **RF23** | Avaliação integrada (matriz T01 a T15) e regressão do Desafio 01 | `src/metrics.py`, `testes/` |
| **RF24** | Privacidade, governança e exclusão demonstrável de documentos | `src/embeddings.py`, `src/app.py` |

