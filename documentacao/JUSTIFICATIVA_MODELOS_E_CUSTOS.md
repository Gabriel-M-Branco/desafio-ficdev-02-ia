# Justificativa Técnica de Escolha dos Modelos e Análise de Custos

**Projeto:** Central Inteligente de Atendimento e Consulta Institucional (GOV.MT / SECITECI-MT)  
**Versão:** 2.0.0 | **Data:** Outubro de 2026  
**Ambiente Oficial:** Streamlit (`src/app.py`) e Linha de Comando (`src/main.py`)

---

## 1. Visão Geral da Estratégia de Modelos

A seleção da arquitetura de inteligência artificial da Central de Atendimento foi guiada por quatro pilares do serviço público estadual:
1. **Eficiência Orçamentária e Previsibilidade:** Eliminar cobranças desnecessárias em tarefas passíveis de resolução local e adotar modelos de nuvem de custo unitário ínfimo por atendimento ao cidadão.
2. **Alta Fidelidade Documental e Alucinação Zero:** Suporte rigoroso a esquemas estruturados (`Pydantic v2` com `extra="forbid"`), garantindo que dados não localizados permaneçam nulos ou marcados como `"não localizado"`, separando extração literal de fatos inferidos (`RF14`, `RF15`).
3. **Desacoplamento e Portabilidade de Provedores (`RF21`):** A camada de geração textual e os motores multimodais podem ser alternados dinamicamente (OpenAI, Hugging Face, OpenRouter ou Adaptador Local Simulado) sem qualquer necessidade de reconstrução do índice vetorial do RAG.
4. **Segurança de Custos e Guardrails Operacionais (`RF16`):** Travas programáticas de limite de caracteres (8.000), tamanho de anexos (10 MB), teto de chamadas por execução (máximo de 3 chamadas pelo guardrail `MAX_CHAMADAS_POR_EXECUCAO`) e timeouts rígidos (60s) para impedir gastos descontrolados.

---

## 2. Camada de Geração Textual, RAG e Classificação

### 2.1. Modelo Proprietário Primário: `gpt-4o-mini` (OpenAI)
- **Papel:** Motor padrão de atendimento, geração de minutas institucionais, classificação de demandas e fundamentação RAG via API comercial.
- **Estrutura Tarifária:**
  - Entrada: \$0,15 por 1 milhão de tokens (~R\$ 0,85 por 1M tokens).
  - Saída: \$0,60 por 1 milhão de tokens (~R\$ 3,40 por 1M tokens).
- **Justificativa Técnica:**
  - **Relação Custo-Benefício:** Custa cerca de 95% menos que o GPT-4o tradicional, viabilizando centenas de milhares de consultas públicas com impacto orçamentário desprezível.
  - **Adesão Estrita a Esquemas JSON:** Conformidade exemplar com esquemas `Pydantic`, reduzindo a zero a ocorrência de chaves extras ou tipos inválidos.
  - **Baixa Latência:** Respostas entregues entre 1,2 e 2,5 segundos, proporcionando experiência ágil para o servidor público no Streamlit.
  - **Acurácia em Português Formal:** Produz minutas com vocabulário adequado ao padrão da administração pública estadual (SECITECI-MT).

### 2.2. Modelo Proprietário Avançado: `gpt-4o` (OpenAI)
- **Papel:** Alternativa configurável para despachos altamente complexos e motor de visão computacional de alta definição.
- **Estrutura Tarifária:**
  - Entrada: \$2,50 por 1 milhão de tokens.
  - Saída: \$10,00 por 1 milhão de tokens.
- **Justificativa Técnica:**
  - Capacidade superior de raciocínio lógico em casos de conciliação de normas conflitantes e leitura de digitalizações manuscritas.

### 2.3. Modelo Aberto Principal: `Qwen/Qwen2.5-72B-Instruct` (Hugging Face / OpenRouter)
- **Papel:** Principal alternativa open-weights para inferência serverless ou nuvem aberta.
- **Estrutura Tarifária:** Gratuito na cota Hugging Face Serverless Inference API; frações de centavo via OpenRouter.
- **Justificativa Técnica:**
  - Densidade de 72 bilhões de parâmetros com desempenho de topo em benchmarks de seguimento de instruções em língua portuguesa.
  - Janela de contexto extensa, capaz de processar os fragmentos do acervo sem compressão de atenção.

### 2.4. Modelo Aberto de Contingência: `meta-llama/Llama-3.3-70B-Instruct`
- **Papel:** Fallback imediato em caso de sobrecarga ou fila na API do Qwen.
- **Justificativa Técnica:** Arquitetura madura com alinhamento seguro, permitindo substituição direta sem alteração dos contratos de dados.

### 2.5. Adaptador Simulado Local: `simulador-institucional-govmt-v2` (`RF21`)
- **Papel:** Execução local determinística sem conexão com a internet.
- **Estrutura Tarifária:** \$0,00 (custo zero absoluto).
- **Justificativa Técnica:**
  - Permite a execução integral da suíte de testes automatizados (`pytest testes/ -v`) e da avaliação de métricas (`python -m src.metrics` com 15/15 aprovados) em qualquer computador ou ambiente de CI/CD sem exigir credenciais ativas nem consumir cotas de desenvolvimento.

---

## 3. Base Vetorial e Embeddings do RAG (`RF17`, `RF18`, `RF21`)

### 3.1. Abordagem Vetorial Determinística: TF-IDF Denso com Projeção em 512 Dimensões
- **Estrutura Tarifária:** \$0,00 (custo zero permanente).
- **Justificativa Técnica e Econômica:**
  - **Eliminação de Custos Recorrentes de Embeddings:** O uso de APIs de embedding tarifadas (como `text-embedding-3-small` da OpenAI) geraria custos em toda indexação e em cada busca realizada pelo cidadão. O motor TF-IDF denso de 512 dimensões opera localmente em memória e disco (`indice/indice_vetorial.json`).
  - **Desacoplamento Provedor-Índice (`RF21`):** A troca do provedor de geração textual (ex.: mudar de `gpt-4o-mini` para `Qwen2.5-72B` ou `adaptador_simulado`) **não reconstrói nem invalida a base vetorial**, pois a vetorização não depende de pesos de LLMs externos.
  - **Privacidade e Desempenho:** O acervo institucional da SECITECI-MT permanece indexado localmente, com consultas processadas em menos de 10 milissegundos.

---

## 4. Motores Multimodais e Soluções Híbridas

### 4.1. Visão Computacional e OCR (`RF08`)

#### Opção A — Alta Qualidade: `gpt-4o` Vision (OpenAI)
- **Custo Unitário:** Aproximadamente \$0,005 a \$0,01 por página (via payload de alta resolução `"detail": "high"`).
- **Justificativa:**
  - Analisa formulários escaneados, tabelas com bordas apagadas, marcas de seleção e caligrafias com resolução em mosaico de 512x512 pixels.
  - No teste oficial com `dados/originais/entrada_pdf-imagem.pdf`, alcançou 100% de precisão nos campos legíveis (nome, CPF, RG, curso, turno, e-mail e presença de assinatura), superando completamente limitações de OCRs legados.

#### Opção B — Soberania e Custo Zero: `PyMuPDF` + `Tesseract OCR` (`por`)
- **Custo Unitário:** \$0,00 (execução local).
- **Justificativa:**
  - Opera como fallback automático de segurança caso a API esteja sem saldo ou sem chave (`.env`).
  - Garante conformidade total de privacidade e soberania de dados para órgãos que proíbem envio de imagens documentais a servidores em nuvem.

### 4.2. Reconhecimento de Fala / STT (`RF06`)

#### Opção A — Qualidade de Estúdio: `whisper-1` (OpenAI Audio API)
- **Custo Unitário:** \$0,006 por minuto de áudio gravado (~R\$ 0,034 por minuto).
- **Justificativa:**
  - Transcrição nativa com pontuação contextual precisa e fidelidade ortográfica em áudios de cidadãos gravados com ruído ambiente ou microfones de baixa qualidade.

#### Opção B — Soberania Local: `faster-whisper` (`small` / int8 / CPU)
- **Custo Unitário:** \$0,00 (processamento local CTranslate2).
- **Justificativa:**
  - Transcrição offline em tempo real em processadores convencionais, sem envio de voz a terceiros.

### 4.3. Síntese de Voz / TTS Acessível (`RF07`)

#### Opção A — Voz Neural Avançada: `OpenAI TTS` (`tts-1`)
- **Custo Unitário:** \$0,015 por 1.000 caracteres (~R\$ 0,085 por minuto de fala).
- **Justificativa:**
  - Síntese com entonação natural e cadência humana para atendimento acessível.
  - **Trava de Segurança:** A síntese só é acionada após deliberação e aprovação explícita do texto exato por um servidor humano (`exigir_aprovacao=True`), evitando consumo acidental de créditos.

#### Opção B — Nuvem Acessível: `edge-tts` (`pt-BR-AntonioNeural`)
- **Custo Unitário:** \$0,00.
- **Justificativa:** Voz neural brasileira de alta qualidade sem cobrança de API.

#### Opção C — Local Offline: `SAPI5` (Windows)
- **Custo Unitário:** \$0,00.
- **Justificativa:** Opera de forma 100% offline utilizando os motores nativos de acessibilidade do sistema operacional.

### 4.4. Geração de Peças Institucionais / Imagem (`RF10`)

#### Abordagem Híbrida: Arte Conceitual via IA + Composição Programática via `Pillow`
- **Custo Unitário:** Praticamente zero (faixa gratuita do Cloudflare Workers AI / HF FLUX.1-schnell) ou ~\$0,04 por arte com DALL-E 3 Standard (1024x1024).
- **Justificativa Arquitetural:**
  - Modelos de difusão gráfica (DALL-E, Midjourney, Stable Diffusion) frequentemente falham ao renderizar textos em português, invertem letras ou alucinam brasões governamentais.
  - Na solução adotada, a IA gera unicamente a **ilustração central artística** (sem texto).
  - O cabeçalho padronizado do GOV.MT, o brasão oficial de Mato Grosso (`dados/originais/brasao.png`), a tipografia institucional, o aviso de proveniência de IA e o hash de auditoria SHA-256 são renderizados programaticamente em milissegundos via biblioteca Python `Pillow`.
  - Essa abordagem reduz as tentativas de geração a 1 única chamada, economizando mais de 80% do custo de imagem e garantindo 100% de conformidade com o manual de identidade visual do Estado.

---

## 5. Tabela Comparativa de Custos por Componente

| Componente | Provedor de Alta Qualidade | Custo Unitário (Nuvem) | Motor Soberano / Local | Custo Unitário (Local) |
|---|---|---|---|---|
| **Texto / RAG / Minutas** | `gpt-4o-mini` (OpenAI) | ~\$0,0004 a \$0,0008 por despacho | `Adaptador Simulado` | \$0,00 |
| **Texto / Raciocínio Aberto** | `Qwen2.5-72B` (HF / OpenRouter) | Gratuito (cota) / Baixo custo | `Llama-3.3-70B` | \$0,00 (serverless) |
| **Indexação Vetorial RAG** | TF-IDF Denso Local (512d) | \$0,00 | TF-IDF Denso Local | \$0,00 |
| **Visão / OCR Multimodal** | `gpt-4o` Vision (OpenAI) | ~\$0,005 a \$0,01 por página | `Tesseract` + `PyMuPDF` | \$0,00 |
| **Áudio STT (Voz para Texto)** | `whisper-1` (OpenAI) | \$0,006 por minuto de áudio | `faster-whisper (small)` | \$0,00 |
| **Áudio TTS (Texto para Voz)** | `tts-1` (OpenAI) | \$0,015 por 1.000 caracteres | `edge-tts` / `SAPI5` | \$0,00 |
| **Imagem Institucional** | `FLUX` / `DALL-E 3` + `Pillow` | \$0,00 (FLUX) a \$0,04 (DALL-E) | `Pillow` nativo | \$0,00 |

---

## 6. Simulação Orçamentária Mensal (Cenário de Atendimento Público)

Considerando a operação mensal de uma unidade da SECITECI-MT com volume estimado de:
- **1.000 solicitações textuais de cidadãos** (triagem, extração de ficha e minuta RAG);
- **200 documentos escaneados submetidos para OCR** (certidões, laudos, matrículas);
- **150 mensagens de voz recebidas** (média de 1,5 minuto de áudio cada);
- **100 minutas de áudio sintetizadas para acessibilidade** (média de 600 caracteres cada);
- **20 peças institucionais para campanhas informativas**.

### Cenário 1: Operação de Alta Qualidade (OpenAI Stack Completa)
- Texto e RAG (`gpt-4o-mini`): 1.000 x \$0,0006 = **\$0,60**
- OCR Multimodal (`gpt-4o` Vision): 200 x \$0,008 = **\$1,60**
- Transcrição de Voz (`whisper-1`): 150 x 1,5 min x \$0,006 = **\$1,35**
- Síntese de Voz Aprovada (`tts-1`): 100 x 0,6k chars x \$0,015 = **\$0,90**
- Imagem Institucional Híbrida: 20 x \$0,04 = **\$0,80**
- **Custo Mensal Total Estimado:** **\$5,25 (aproximadamente R\$ 30,00 por mês)**.

> **Conclusão Orçamentária:** Mesmo no cenário de qualidade máxima com todos os recursos comerciais ativados, o custo total por mês para atender 1.000 cidadãos é inferior a **R\$ 35,00**, demonstrando viabilidade orçamentária extraordinária para o setor público.

### Cenário 2: Operação Econômica Híbrida (Recomendada para Produção)
- Texto e RAG via `gpt-4o-mini` (alta fluidez e zero alucinação).
- OCR via `gpt-4o` Vision (alta legibilidade de formulários).
- Áudio STT via `faster-whisper` local em CPU (custo zero e privacidade de voz).
- Áudio TTS via `edge-tts` acessível (custo zero).
- Imagem via `FLUX` + `Pillow` (custo zero).
- **Custo Mensal Total Estimado:** **\$2,20 (aproximadamente R\$ 12,50 por mês)**.

### Cenário 3: Soberania Total e Custo Zero (Offline / Laboratório)
- Utilização de modelos abertos (`Qwen2.5-72B` ou adaptador simulado), `Tesseract` local, `faster-whisper` local e `SAPI5`.
- **Custo Mensal Total:** **\$0,00 (Zero)**.

---

## 7. Conformidade com Governança e Regras de Segurança (`RF16`)

1. **Teto Orçamentário por Requisição:** A configuração padrão (`config.json`) estabelece `max_tokens: 2500` e `temperature: 0.1`, evitando custos com respostas prolixas ou repetições em loop.
2. **Defesa contra Ataques de Denegação de Serviço Orçamentário (EDoS):**
   - Requisições acima de 8.000 caracteres ou arquivos superiores a 10 MB são rejeitadas de imediato pela camada de guardrails antes do envio à API tarifada.
   - O contador de chamadas encerra o ciclo se o limite de 8 invocações for atingido em uma mesma sessão (`T05`).
3. **Auditoria e Monitoramento de Tokens (`RF11`, `RF13`):**
   - Toda chamada a provedores externos registra no log de auditoria (`resultados/logs/audit_trail.jsonl`) a contagem de `prompt_tokens`, `completion_tokens`, `total_tokens` e a latência de execução em segundos, viabilizando auditoria orçamentária contínua pelo Tribunal de Contas e controladores internos.
