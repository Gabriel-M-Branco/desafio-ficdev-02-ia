# Relatório Técnico — Central Inteligente de Atendimento e Consulta Institucional (GOV.MT)

> **Atualização após auditoria:** as afirmações e taxas abaixo pertencem ao relatório
> anterior. O comportamento corrigido, suas limitações e as evidências atuais estão
> em [CORRECOES_D02.md](CORRECOES_D02.md) e em `evidencias/validacao_d02.json`.

**Programa:** FIC_DEV — Programador de Sistemas com IA (2026)  
**Projeto:** Desafios Práticos 01 (`RF01–RF13`) e 02 (`RF14–RF24`) — Central Inteligente de Atendimento e Consulta Institucional  
**Órgão Atendido (Fictício):** Governo do Estado de Mato Grosso / SECITECI-MT / ETEC Cuiabá  
**Versão:** 2.0.0  

---

## 1. Visão Geral e Evolução Arquitetural (Desafio 01 $\rightarrow$ Desafio 02)

O sistema evoluiu de uma central multimodal de triagem (Desafio 01) para uma **Central Integrada de Atendimento, Extração Estruturada Validada, Consulta Documental Fundamentada (RAG) e Análise de Sentimentos** (Desafio 02), tendo o **Streamlit (`src/app.py`)** como única interface oficial consolidada.

### Princípios Arquiteturais Centrais:
1. **Interface Oficial Única em Streamlit (`RF20`):** Consolida todos os 9 módulos operacionais em uma única experiência interativa para o servidor público, eliminando interfaces paralelas legadas.
2. **Contratos de Dados Estritos com Pydantic v2 (`RF14`, `RF15`):** Todos os modelos (`ExtracaoFicha`, `TrechoRecuperado`, `RespostaRAG`, `ClassificacaoSentimento`, `DecisaoOperador`) utilizam `ConfigDict(extra="forbid")`, representam ausências como `null` no schema (convertendo para `"não localizado"` na camada de apresentação), validam coerência factual contra o texto de origem e separam **extração literal** de **informação inferida**.
3. **RAG Fundamentado com Precedência e Detecção de Conflitos (`RF17`, `RF18`, `RF19`):** Indexação persistente de 6 documentos institucionais (`3 .txt` e `3 .pdf` em `dados/acervo/`), recuperação `top-k` com similaridade e distância, sanitização contra injeção indireta no corpus (`ADV-02`), citação obrigatória de metadados e separação explícita entre fatos relatados pelo cidadão e regras do acervo na geração de minutas.
4. **Provedores de IA Configuráveis sem Reconstrução do Índice (`RF04`, `RF21`):** Suporte a `OpenAI API` (`gpt-4o-mini`), `OpenRouter API`, `Hugging Face Serverless API` e `Adaptador Simulado Identificado` (`adaptador_simulado`), permitindo alternar a camada de geração preservando intacta a base vetorial (`indice/indice_vetorial.json`).
5. **Governança Humana (*Human-in-the-Loop*) e LGPD (`RF11`–`RF13`, `RF21`, `RF24`):** Nenhuma resposta oficial, síntese de áudio (`RF07`) ou peça visual (`RF10`) é publicada sem aprovação humana justificada e auditada, com mascaramento automático de CPF, e-mail e chaves de API nos logs e suporte a expurgo demonstrável de documentos do índice vetorial.

---

## 2. Experimento Comparativo de Chunking e Recuperação (`RF18` / `T07`)

Foram avaliadas duas configurações distintas de segmentação documental sobre os mesmos 6 documentos do acervo (`DOC-SECITECI-001` a `DOC-SECITECI-006`), mantendo fixos o modelo vetorial (`tfidf-dense-pt`, dimensão `512`) e `top_k = 3`:

| Configuração | Tamanho do Chunk | Sobreposição (Overlap) | Total de Chunks Gerados | Acerto Top-3 (`P1` a `P5`) | Taxa de Acerto |
|---|---|---|---|---|---|
| **Configuração A (Adotada)** | `400` caracteres | `80` caracteres | `49` fragmentos | `5 / 5` | **100.0%** |
| **Configuração B (Comparativa)** | `800` caracteres | `150` caracteres | `24` fragmentos | `5 / 5` | **100.0%** |

**Justificativa Técnica da Escolha (`Configuração A`):** A Configuração A (`400` caracteres com sobreposição de `80`) isola com maior precisão artigos normativos individuais (como o Art. 2º do `DOC-SECITECI-002` sobre o formato `.mp4` e duração de até 2 minutos do vídeo de heteroidentificação, e o Art. 7º do `DOC-SECITECI-004` sobre o 5º dia útil), reduzindo o ruído lexical nas citações apresentadas ao operador humano e mantendo 100% de revocação no `top-3`.

---

## 3. Avaliação dos Cenários Mínimos Obrigatórios e Matriz `T01` a `T15` (`RF23`)

A execução automatizada (`python -m src.metrics` e `pytest testes/ -v`) comprova 100% de aprovação nos 15 testes da matriz obrigatória:

- **6 Solicitações Fictícias (`SOL-01` a `SOL-06` — `RF14`/`RF15`/`T03`):**
  - Acurácia de categoria: **100.0% (`6/6`)**
  - Resumos fiéis `<= 100` palavras: **6/6**
  - Fatos sem suporte no texto original: **0**
  - Casos incompletos (`SOL-05`) e ambíguos entre polos Cuiabá/Barra do Garças (`SOL-06`) marcados automaticamente com `necessidade_revisao = True`.
- **8 Perguntas de Avaliação RAG (`P1` a `P8` — `RF19`/`T08`–`T10`):**
  - 5 perguntas respondíveis (`P1` a `P5`): **5/5** com status `fundamentada` e citação da fonte correta (priorizando `DOC-SECITECI-002` v2.0 sobre `DOC-SECITECI-001` v1.0 quando aplicável).
  - 2 perguntas sem resposta no corpus (`P6`, `P7`): **2/2** com status `sem_evidencia_suficiente`, abstenção segura e `necessidade_revisao = True`.
  - 1 pergunta com fontes contraditórias (`P8` — entrega de frequência do Auxílio Alimentação até o 5º dia útil em `DOC-SECITECI-004` vs até o dia 15 em `DOC-SECITECI-006`): **1/1** com status `conflito_de_fontes`, explicitação das duas normas divergentes e encaminhamento humano.
- **12 Avaliações de Sentimento (`AV-01` a `AV-12` — `RF22`/`T13`):**
  - Acurácia de classificação: **100.0% (`12/12`)** (`3` positivas, `3` negativas, `3` neutras, `3` indeterminadas/mistas/irônicas com `necessidade_revisao = True`).
  - Agregação matemática determinística em Python com filtros por categoria/canal e período, deduplicação por `id` e proteção contra divisão por zero em conjuntos vazios.
- **3 Entradas Adversariais (`ADV-01`, `ADV-02`, `ADV-03` — `RF16`/`T04`):**
  - **3/3 neutralizadas** (bloqueio de prompt injection direta na solicitação, sanitização de instrução oculta `<!-- SYSTEM INSTRUCTION ... -->` no corpus recuperado e bloqueio de tentativa de exfiltração de `HF_TOKEN`, `OPENAI_API_KEY` e `OPENROUTER_API_KEY`).

---

## 4. Governança, Privacidade (LGPD) e Exclusão de Documentos (`RF12`, `RF21`, `RF24`)

1. **Minimização e Mascaramento:** CPFs e e-mails são mascarados nos logs (`123.***.***-00`, `m***@email.ficticio.br`), e contadores numéricos de uso (`max_tokens`, `prompt_tokens`, `completion_tokens`, `total_tokens`) são preservados sem redigir indevidamente valores numéricos, enquanto credenciais (`HF_TOKEN`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`) jamais são gravadas em disco.
2. **Direito de Exclusão / Expurgo Vetorial (`T14`):** O método `IndiceVetorial.excluir_documento(documento_id)` remove todos os chunks e vetores associados a um documento e reconstrói a matriz TF-IDF, garantindo que trechos expurgados deixem imediatamente de ser recuperados pelo RAG.

---

## 5. Justificativa de Modelos e Viabilidade de Custos

A seleção de modelos e a arquitetura de inferência encontram-se integralmente detalhadas em [JUSTIFICATIVA_MODELOS_E_CUSTOS.md](JUSTIFICATIVA_MODELOS_E_CUSTOS.md), pautadas em eficiência orçamentária para o serviço público estadual:
- **Camada Textual e RAG:** Adoção de `gpt-4o-mini` como modelo comercial padrão (~US$ 0,15/1M input tokens e US$ 0,60/1M output tokens), com suporte a `Qwen2.5-72B` (open-weights) e adaptador simulado local identificado para testes sem custo de API (`T12`).
- **Base Vetorial Soberana:** TF-IDF denso de 512 dimensões com persistência JSON local, eliminando tarifas recorrentes de APIs de embedding e desacoplando o índice do provedor LLM (`RF21`).
- **Multimodalidade Híbrida e Soberana:** Visão de alta fidelidade via `gpt-4o` Vision com fallback para `Tesseract` e `PyMuPDF` local; transcrição de voz com `whisper-1` ou `faster-whisper` local em CPU; síntese acessível com trava humana prévia; e geração híbrida de artes institucionais (`FLUX` ou `DALL-E` para ilustração central + `Pillow` para diagramação oficial do GOV.MT).
- **Projeção Orçamentária:** A simulação de 1.000 atendimentos mensais projeta custo entre R$ 12,50 e R$ 30,00 na modalidade comercial, ou R$ 0,00 na modalidade totalmente local/soberana.

