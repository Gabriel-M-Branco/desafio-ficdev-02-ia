# Registro de Uso da Inteligência Artificial no Desenvolvimento (Seção 10 do Edital)

**Programa:** FIC_DEV — Programador de Sistemas com IA (2026)
**Projeto:** Central Inteligente de Atendimento e Comunicação Institucional (GOV.MT)
**Equipe de Desenvolvimento:** Discentes do FIC_DEV

> Registro historico do desenvolvimento. Provedores e resultados atuais: consulte README.md e os registros de cada execucao; nao usar este historico como comprovacao da integracao.

---

## 1. Ferramentas, Modelos e Versões Utilizados

No processo de desenvolvimento assistido, foram utilizadas as seguintes ferramentas de engenharia de software e inteligência artificial:
- **Assistente de Codificação:** Antigravity AI Coding Agent (Google DeepMind)
- **Modelos de Linguagem e Raciocínio Utilizados:**
  - `Gemini 2.5 Pro` e `Gemini 3.8 Flash (High)` para raciocínio de arquitetura e codificação;
  - `Qwen/Qwen2.5-72B-Instruct` (via Hugging Face Serverless) para extração estruturada e minutas institucionais;
  - `Qwen/Qwen2.5-VL-7B-Instruct` para visão multimodal de documentos digitalizados;
  - `openai/whisper-large-v3-turbo` para transcrição de fala (STT);
  - `black-forest-labs/FLUX.1-schnell` para geração de ilustração vetorial sem texto;
  - `edge-tts` (voz neural `pt-BR-AntonioNeural`) para síntese de voz acessível.
- **Ambiente de Execução e Testes:** Python 3.14 / Python 3.11-slim (Docker), FastAPI 0.110+, Pillow 10.2+, PyMuPDF 1.24+, Pytest 9.1+.

---

## 2. Solicitações Relevantes Feitas à IA

### Solicitação 1: Arquitetura de Blindagem contra Prompt Injection e Alucinação
* **Prompt Enviado:**
  *"Projete uma estratégia de engenharia de prompts que separe estritamente as instruções institucionais do sistema do conteúdo fornecido pelo cidadão, impedindo ataques de injeção de prompt e garantindo que campos ausentes recebam compulsoriamente o valor 'não localizado' sem qualquer alucinação."*
* **Resultado:**
  Criação da estrutura de envelope semântico `<conteudo_nao_confiavel>...</conteudo_nao_confiavel>` no Prompt C e no módulo `prompts.py`, com validação estruturada em JSON e regras determinísticas.

### Solicitação 2: Estratégia Híbrida para Geração da Peça Visual Institucional GOV.MT
* **Prompt Enviado:**
  *"Como garantir que a peça visual gerada cumpra o manual de identidade visual do GOV.MT (azul #004A8F, verde #008B47, amarelo #F7B500), contenha o brasão oficial nítido e a tarja de proveniência de conteúdo sintético, sabendo que modelos de difusão frequentemente erram textos e heráldica?"*
* **Resultado:**
  Adoção de abordagem híbrida em dois estágios: o modelo de difusão (`FLUX.1-schnell`) gera apenas a ilustração artística central sem nenhum caractere ou texto (`no text, no words, no letters`), e o Python (`Pillow`) realiza a composição tipográfica vetorial exata, colando o brasão oficial de `dados/originais/brasao.png` e a tarja obrigatória de proveniência.

### Solicitação 3: Implementação de Acessibilidade com Filtro Auditivo de Ausências
* **Prompt Enviado:**
  *"Como implementar o recurso de síntese de voz (TTS) para acessibilidade institucional garantindo que valores marcados como 'não localizado' não soem confusos ou sejam omitidos pelo leitor de tela?"*
* **Resultado:**
  Implementação no módulo `src/audio.py` de um pré-processador fonético que substitui ou precede a expressão "não localizado" por uma notificação formal explícita ao ouvinte: *"Atenção: informação pendente de localização no sistema"*, assegurando clareza e transparência auditiva.

---

## 3. Sugestões Aceitas, Modificadas e Rejeitadas

* **Sugestões Aceitas:**
  - Utilização do `FastAPI` servindo frontend Vanilla (HTML/CSS/JS) sem complexidade desnecessária de frameworks pesados, garantindo execução leve e compatibilidade imediata em qualquer ambiente corporativo.
  - Implementação de um motor de contingência/mock offline inteligente no `LLMClient`, permitindo rodar a aplicação e demonstrar todos os requisitos mesmo em máquinas sem conexão externa ou sem chave de API configurada.
  - Utilização do `PyMuPDF` (`pymupdf`) para converter páginas de PDF em imagem de alta resolução em memória, eliminando a dependência de binários externos do Poppler no Windows.

* **Sugestões Modificadas:**
  - *Sugestão da IA:* Gerar o texto do comunicado visual diretamente dentro da imagem com o modelo FLUX.1.
    *Modificação da Equipe:* **Rejeitada a geração de texto por difusão**, pois gerava artefatos ilegíveis. Optou-se pela abordagem híbrida estrita: IA para a ilustração e Pillow para a moldura, tipografia, brasão e tarja de proveniência.
  - *Sugestão da IA:* Realizar validação de datas na transcrição de áudio por correspondência exata de string.
    *Modificação da Equipe:* Ajustada para considerar formatos por extenso ("14 de outubro de 2026") e numérico ("14/10/2026"), refletindo a realidade da fala humana.

* **Sugestões Rejeitadas:**
  - Sugestão de envio automático de e-mail ao cidadão após a geração da minuta. Rejeitada categoricamente em respeito ao Artigo 3 do Edital, que veda qualquer despacho autônomo sem homologação humana prévia.

---

## 4. Erros e Inadequações Encontrados

1. **Tentativa de importação de módulos ausentes no pytest:** O pytest inicialmente não encontrava o pacote `src` devido ao `PYTHONPATH`. Foi corrigido com a criação do arquivo canônico `pytest.ini` definindo `pythonpath = .`.
2. **Discrepância na conferência de datas no áudio:** O gabarito possuía a data em formato numérico e o áudio falado expressava a data por extenso. A lógica de verificação foi aprimorada para normalizar datas antes do cálculo de acurácia.
3. **Imutabilidade de `dados/originais/`:** Durante um teste preliminar, gerou-se um arquivo temporário dentro da pasta de originais. O arquivo foi imediatamente removido e a rotina redirecionada para `dados/processados/` para preservar rigorosamente a integridade dos dados originais.

---

## 5. Forma de Validação do Código e Conteúdo Gerado

O código e os artefatos foram submetidos a validação em múltiplas camadas:
- **Testes Automatizados Unitários e de Integração:** 12 testes executados via `pytest` cobrindo desde a leitura de configurações, tratamento de exceções, extração estruturada, STT, TTS, visão computacional até a gravação dos logs de auditoria e conformidade LGPD.
- **Execução Integral de Pipeline (--run-all):** Verificação de ponta a ponta gerando todos os arquivos de saída em `dados/processados/`, `resultados/` e `prompts/`.
- **Inspeção Visual e Auditiva Humana:** Conferência manual da peça gráfica gerada em `resultados/imagens/comunicado_institucional_govmt.png` e audição do arquivo de áudio acessível sintetizado em `resultados/audios/minuta_aprovada_acessivel.mp3`.
- **Inspeção de Segurança e Credenciais:** Varredura em todo o código e logs garantindo ausência de chaves de API versionadas ou dados pessoais reais.

---

## 6. Declaração de Responsabilidade da Equipe

Declaramos formalmente que toda a solução entregue neste repositório foi planejada, compreendida, testada e validada pela equipe discente. O uso de ferramentas de inteligência artificial ocorreu estritamente como suporte técnico e pedagógico para produtividade e aceleração de desenvolvimento, permanecendo a responsabilidade integral sobre as decisões de arquitetura, qualidade do código, veracidade das evidências e conformidade institucional com a equipe.
