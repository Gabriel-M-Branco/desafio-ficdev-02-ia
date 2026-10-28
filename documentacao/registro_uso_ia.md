# Registro de Uso da Inteligência Artificial no Desenvolvimento (Seção 10 do Edital)

**Programa:** FIC_DEV — Programador de Sistemas com IA (2026)  
**Projeto:** Central Inteligente de Atendimento e Consulta Institucional (GOV.MT) — Desafios 01 e 02  
**Equipe de Desenvolvimento:** Gabriel Moreira Branco, Emilly Caroline dos Santos Arruda e Marcos Vinícius G. S. Campos

---

## 1. Ferramentas, Modelos e Versões Utilizados

No processo de desenvolvimento assistido dos Desafios Práticos 01 e 02, foram utilizadas as seguintes ferramentas de engenharia de software e inteligência artificial:
- **Assistente de Codificação e Auditoria Arquitetural:** Antigravity AI Coding Agent (Google DeepMind)
- **Modelos de Linguagem e Raciocínio Suportados na Arquitetura:**
  - `OpenAI API` (`gpt-4o-mini`) configurável via `OPENAI_API_KEY`;
  - `Qwen/Qwen2.5-72B-Instruct` (via Hugging Face Serverless API) e `meta-llama/Llama-3.3-70B-Instruct:free` / `google/gemini-3.8-flash` (via OpenRouter);
  - `openai/whisper-large-v3-turbo` / `faster-whisper` para transcrição de fala (STT);
  - `black-forest-labs/FLUX.1-schnell` + `Pillow` para geração híbrida de peça visual institucional;
  - `edge-tts` (`pt-BR-AntonioNeural`) e `SAPI5` para síntese de voz acessível condicionada à aprovação humana.
- **Stack de Dados, Validação, RAG e Testes:** Python 3.11+, Streamlit, FastAPI, Pydantic v2, scikit-learn, PyMuPDF, Tesseract OCR, Pytest (316+ testes automatizados).

---

## 2. Solicitações Relevantes Feitas à IA no Desafio 02

### Solicitação 1: Auditoria de Artefatos e Correção de Truncamento em PDFs do Acervo (`RF17`, `RF18`)
* **Contexto:** Durante a auditoria técnica inicial do Desafio 02, identificou-se que os PDFs gerados em `dados/acervo/` (`DOC-SECITECI-002`, `004` e `006`) haviam sido criados com `page.insert_text` sem quebra automática de linha, truncando horizontalmente prazos e regras críticas.
* **Solução Implementada e Validada:** Regeneração controlada dos 3 PDFs em `dados/acervo/` utilizando `page.insert_textbox` no `PyMuPDF` (preservando `dados/originais/` 100% intocado) e reconstrução completa de `indice/indice_vetorial.json` com 49 fragmentos íntegros.

### Solicitação 2: Contratos Pydantic v2 Estritos e Separação Literal vs. Inferido (`RF14`, `RF15`)
* **Contexto:** Necessidade de impedir chaves extras inventadas pelo modelo, validar coerência factual com o texto da solicitação e separar o que foi extraído literalmente do que foi inferido pela triagem.
* **Solução Implementada e Validada:** Uso de `ConfigDict(extra="forbid")` em `src/schemas.py`, validador de coerência textual em `ExtracaoFicha`, método `separar_literal_e_inferido()` e comparador `comparar_json_sintatico_vs_esquema()`.

### Solicitação 3: Defesa contra Prompt Injection Indireta no Corpus RAG (`RF16`, `RF19`)
* **Contexto:** Documentos indexados podem conter comentários ocultos maliciosos (`ADV-02`).
* **Solução Implementada e Validada:** Implementação de `GuardrailManager.sanitizar_documento_recuperado()` envolvendo trechos recuperados em `<documento_recuperado>` e removendo instruções ocultas antes da síntese da resposta e da minuta fundamentada.

---

## 3. Forma de Validação do Código e dos Artefatos Gerados

1. **Matriz Automatizada `T01` a `T15` (`python -m src.metrics`):** 15/15 testes aprovados, validando extração estruturada, sumarização, guardrails, deduplicação vetorial, comparativo de chunking (`Config A` vs `Config B`), RAG respondível/abstenção/conflito, atendimento integrado, troca de provedor sem reindexar, sentimentos, expurgo de documento e ausência de regressão.
2. **Suíte Completa `pytest testes/ -v`:** Mais de 315 testes automatizados cobrindo todos os requisitos `RF01` a `RF24`.

---

## 4. Declaração de Responsabilidade da Equipe

Declaramos formalmente que toda a solução entregue neste repositório foi planejada, compreendida, testada e validada pela equipe discente. O uso de ferramentas de inteligência artificial ocorreu estritamente como suporte técnico e pedagógico, permanecendo a responsabilidade integral sobre as decisões de arquitetura, qualidade do código, veracidade das evidências e conformidade institucional com a equipe.
