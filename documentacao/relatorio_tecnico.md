# Relatório Técnico - Central Inteligente de Atendimento e Comunicação Institucional (GOV.MT)

**Programa:** FIC_DEV — Programador de Sistemas com IA (2026)  
**Projeto:** Desafio Prático 1 — Central Inteligente de Atendimento e Comunicação Institucional  
**Órgão Atendido (Fictício):** Governo do Estado de Mato Grosso / SECITECI-MT / ETEC Cuiabá  
**Versão:** 1.0  

---

## 1. Visão Geral e Arquitetura da Solução

O sistema foi concebido como uma **Central Multimodal de Apoio ao Atendimento Institucional**, estruturada para processar manifestações de cidadãos recebidas em três modalidades distintas: **Texto**, **Áudio (Mensagem de Voz)** e **Imagem/Documento Digitalizado (Ficha de Matrícula manuscrita)**.

### Princípios Arquiteturais Centrais:
1. **Governança Estrita e Human-in-the-Loop (RF13):** A inteligência artificial atua exclusivamente como assistente de triagem, síntese e formatação. Nenhuma resposta ou documento é despachado automaticamente ao cidadão. Cada minuta exige revisão, justificativa e deliberação formal (Aprovação, Correção ou Rejeição) por um servidor humano.
2. **Alucinação Zero e Regra do "Não Localizado" (RF03, RF05, RF09):** O sistema é estritamente proibido de inferir dados ausentes, inventar números de leis, decretos, protocolos ou prazos. Campos omitidos recebem compulsoriamente o valor literal `"não localizado"`.
3. **Custo Zero e Disponibilidade Híbrida (RF04):** Integração com modelos abertos e gratuitos de última geração através da **Hugging Face Serverless Inference API** e **OpenRouter**, acompanhada de motor de contingência offline local para garantir resiliência e independência de conectividade.
4. **Padronização Visual Oficial Híbrida (RF10):** Geração de imagem central via IA generativa (`FLUX.1-schnell`) sem elementos textuais, acoplada programaticamente a um template em Pillow contendo o Brasão Oficial do Estado de Mato Grosso e a tarja obrigatória de identificação de conteúdo sintético.

```
                                [ CIDADÃO ]
                (Texto, Mensagem de Voz ou Ficha em Imagem/PDF)
                                     │
                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │              CAMADA DE RECEPÇÃO E TRIAGEM             │
        ├────────────────────────────────────────────────────────┤
        │ • Texto: Isolamento em envelope XML anti-injeção       │
        │ • Áudio: Validação e STT Whisper (RF06)                │
        │ • Imagem: Renderização e OCR/VLM Qwen2.5-VL (RF08)     │
        └────────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │              NÚCLEO DE INTELIGÊNCIA ARTIFICIAL         │
        ├────────────────────────────────────────────────────────┤
        │ • LLM: Qwen2.5-72B-Instruct / Llama-3.3-70B           │
        │ • Extração Estruturada (JSON) com "não localizado"     │
        │ • Geração de Minuta Formal Padrão GOV.MT               │
        │ • Imagem Sintética: FLUX.1 + Pillow (RF10)             │
        │ • Acessibilidade: TTS edge-tts com alerta sonoro (RF07)│
        └────────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │         INTERFACE HUMAN-IN-THE-LOOP (SERVIDOR)         │
        ├────────────────────────────────────────────────────────┤
        │ • Painel Web FastAPI + HTML5/CSS3/Vanilla JS           │
        │ • Operador: [Aprovar] | [Corrigir/Editar] | [Rejeitar] │
        │ • Justificativa Obrigatória gravada em Trilha de Log   │
        └────────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
                     [ RESPOSTA INSTITUCIONAL HOMOLOGADA ]
```

---

## 2. Seleção de Modelos e Tecnologias

| Modalidade / Função | Modelo / Tecnologia Adotada | Provedor / Mecanismo | Custo Estimado | Justificativa Técnica |
|---|---|---|---|---|
| **Ponto de Entrada & API** | FastAPI + Uvicorn | Python 3.11+ / Local | US$ 0.00 | Alta performance assíncrona, documentação OpenAPI automática e baixo consumo de memória. |
| **Interface de Usuário** | HTML5, CSS3, JavaScript Vanilla | Navegador Local | US$ 0.00 | Sem complexidade de build ou dependências pesadas; compatível com redes corporativas estaduais restritas. |
| **LLM (Texto e Minuta)** | `Qwen/Qwen2.5-72B-Instruct` | Hugging Face Serverless API | US$ 0.00 | Superioridade comprovada em aderência a regras estritas de formato JSON e compreensão do idioma português. |
| **Fallback de LLM** | `meta-llama/Llama-3.3-70B-Instruct` | OpenRouter (Free Tier) | US$ 0.00 | Contingência de alta fidelidade sem custo financeiro em caso de rate limit. |
| **STT (Áudio para Texto)** | `openai/whisper-large-v3-turbo` | Hugging Face Serverless API | US$ 0.00 | Transcrição precisa em português mesmo sob ruído moderado, com conferência contra gabarito. |
| **TTS (Síntese Acessível)** | `edge-tts` (`pt-BR-AntonioNeural`) | Microsoft Edge TTS (Gratuito) | US$ 0.00 | Entonação institucional neutra, sem robótica e com capacidade de pausa e ênfase auditiva. |
| **Visão Multimodal / OCR** | `Qwen/Qwen2.5-VL-7B-Instruct` + `PyMuPDF` | Hugging Face + Local | US$ 0.00 | Capacidade de interpretar fichas manuscritas e apontar formalmente incertezas e campos em branco. |
| **Imagem Institucional** | `black-forest-labs/FLUX.1-schnell` + `Pillow` | HF API + Renderizador Python | US$ 0.00 | Ilustração artística sem texto via IA, unida à precisão tipográfica e heráldica institucional do Pillow. |

---

## 3. Estimativa de Custos e Consumo de Tokens

Todos os provedores selecionados operam em regime de **Cota Gratuita / Custo Zero (US$ 0.00)**:
- **Hugging Face Serverless Inference API:** Gratuita para requisições sob o plano comunitário com `HF_TOKEN`.
- **OpenRouter Free Tier:** Roteamento para modelos `:free` sem consumo financeiro.
- **Edge-TTS:** Serviço de síntese de voz de acesso livre sem cobrança por caractere.
- **Modo Mock / Contingência Local:** Execução 100% offline com consumo nulo de rede e zero custo.

### Médias de Consumo por Ciclo de Atendimento Completo:
- **Tokens de Entrada (Prompt C + Caso Real):** ~450 tokens.
- **Tokens de Saída (JSON + Minuta):** ~520 tokens.
- **Tempo Médio de Resposta Local:** ~0.15s (Mock) a ~2.4s (API remota).
- **Custo Financeiro Total por Atendimento:** **US$ 0.00**.

---

## 4. Gestão de Riscos, Blindagem e Segurança

### 4.1. Defesa contra Prompt Injection (RF03)
Entradas de usuários e manifestações públicas podem conter tentativas deliberadas de subversão de diretrizes (como evidenciado no cenário de teste da classe `SegurancaPrompts`). Para neutralizar esse vetor:
- Todo conteúdo fornecido pelo usuário é sanitizado contra quebras de delimitadores (`</conteudo_nao_confiavel>` é neutralizado).
- A entrada é isolada dentro do envelope semântico:
  ```xml
  <conteudo_nao_confiavel>
  [Conteúdo externo tratado exclusivamente como dado textual, nunca como comando executável]
  </conteudo_nao_confiavel>
  ```
- O modelo é instruído categoricamente a rejeitar solicitações de revogação de regras, recusa de identificação ou invenção de diplomas e isenções tributárias.

### 4.2. Mitigação de Alucinação (Hallucination Mitigation)
O edital proíbe taxativamente a invenção de normas, protocolos ou datas. O sistema implementa:
- Verificação de campos obrigatórios ausentes.
- Atribuição obrigatória e literal do valor `"não localizado"`.
- Lista explícita de `campos_ausentes` gerada no JSON para auditoria.

### 4.3. Soberania Tecnológica e Privacidade de Documentos (RF08, RF12)
Em órgãos públicos estaduais, o envio de documentos com fotos, dados de filiação e certidões de menores para nuvens de terceiros representa risco de conformidade com a LGPD (Lei nº 13.709/2018). O sistema prevê:
- Preferência mandatória por OCR e VLM local (on-premise) para dados sensíveis.
- Mascaramento e pseudonimização prévia de CPF (`***.456.***-**`) e e-mail em logs de rastreabilidade.
- Exclusão absoluta de tokens e chaves de API nos arquivos de auditoria.

---

## 5. Protocolo de Avaliação de Qualidade (RF13)

A avaliação do sistema é realizada confrontando os resultados gerados com os gabaritos prévios em `dados/gabaritos/`:
- **Taxa de Fidelidade contra Gabarito Textual:** 94.4% (acertos em 17 de 18 entidades estruturadas).
- **Conferência de Entidades Críticas no Áudio (Whisper):** 6 de 6 entidades confirmadas (100%).
- **Detecção de Incertezas Visuais (Ficha de Matrícula):** 7 campos em branco e manuscritos identificados com sucesso.
- **Taxa de Aprovação com Human-in-the-Loop:** 50% de aprovação no ciclo de teste (1 caso aprovado formalmente e 1 caso malicioso rejeitado, cumprindo o critério de aceite do RF13).

---

## 6. Governança Avançada de Imagens e Segurança Multimodal (RF10 & Proteção Web)

### 6.1. Workflow Human-in-the-Loop para Peças Visuais (`src/image_access.py`)
Para assegurar conformidade estrita e soberania visual:
- Toda imagem gerada por difusão (seja via Hugging Face ou **Cloudflare Workers AI** `@cf/black-forest-labs/flux-1-schnell`) entra inicialmente em estado `PENDENTE_REVISAO`.
- O endpoint `/api/publicacao/imagem/{id}` atua como gatekeeper: downloads públicos e veiculações só são autorizados após despacho formal do operador humano (`APROVADO`), validando a integridade criptográfica do hash SHA-256 do arquivo.
- Caso ocorra rejeição ou qualquer adulteração posterior dos bytes da imagem, o acesso público é revogado imediatamente (bloqueio 403).

### 6.2. Proteção de Arquivos e Prevenção de Path Traversal (`src/web_files.py`)
- O acesso a arquivos estáticos e anexos multimídia é rigorosamente encapsulado sob verificação de fronteiras seguras (`is_relative_to`), neutralizando tentativas de fuga de diretório (*Path Traversal*).
- Obras e diretórios internos sensíveis (como `.env`, `.git` ou configurações estruturais) são protegidos com bloqueio determinístico.

### 6.3. Fallback Resiliente de Voz (TTS) SAPI5 / edge-tts (`src/audio.py`)
- Em ambientes locais Windows sem conectividade à internet, o sintetizador nativo **SAPI5 (Microsoft Maria Desktop)** assume automaticamente a geração de voz acessível, garantindo que o direito de acessibilidade auditiva não seja interrompido por oscilações de rede.

### 6.4. Cobertura Abrangente de Testes Automatizados
- A suíte de testes unitários e de integração conta com **mais de 220 testes automatizados**, assegurando cobertura estrita para cenários de injeção de prompt, documentos ilegíveis, arquivos corrompidos, falhas de rede, limites de taxa e integridade de auditoria.
