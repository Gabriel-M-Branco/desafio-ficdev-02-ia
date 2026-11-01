# Relatório de Inconsistências Documentais e Decisões Técnicas

**Contexto:** Desafios Práticos 01 e 02 — Central Inteligente de Atendimento e Consulta Institucional (GOV.MT / SECITECI-MT)  
**Objetivo:** Mapear todas as inconsistências identificadas nos editais originais brutos, nas solicitações dos cidadãos e no histórico do acervo, detalhando exatamente as medidas adotadas para saneamento e governança do RAG.

---

## 1. Visão Geral da Separação entre "Originais" e "Acervo"

- **`dados/originais/editais/` (Imutável):** Contém os arquivos brutos fornecidos pela banca/órgão (`Edital Base 006/2026` e `Editais Retificadores 01 a 06`). Por determinação contratual e de auditoria, **nenhum byte desses arquivos foi alterado** (hashes SHA-256 preservados e auditados).
- **`dados/acervo/` (Base do RAG):** Acervo institucional estruturado criado para atender aos requisitos `RF17`, `RF18` e `RF19`. Apresenta cabeçalhos formais de metadados (`IDENTIFICADOR`, `TITULO`, `VERSAO`), limpeza textual para evitar ruídos de OCR/PDF e atende à regra obrigatória da Seção 6 do edital: **mínimo de 2 formatos (`.txt` e `.pdf`), 2 temas institucionais distintos e presença de cenário conflitante**.

---

## 2. Inconsistências nos Editais Oficiais Originais e Soluções Adotadas

| Item / Documento Original | Inconsistência Encontrada | Impacto no RAG / Processo | Medida Adotada / Tratamento no Acervo |
| :--- | :--- | :--- | :--- |
| **Edital 006/2026**<br>Item 5 (Cronograma, pág. 8)<br>e **Retificador 03** (pág. 2) | **Duplicação de numeração e inversão cronológica:**<br>Os itens `19` e `20` aparecem duas vezes. O início das aulas foi marcado para `21/07`, mas a 4ª chamada aparecia depois (`22/07`). | Conflito na ordem de chamadas de vagas remanescentes e ambiguidade no índice. | O próprio órgão publicou o **Edital Retificador nº 05**, antecipando a 4ª chamada para `03/07 a 08/07/2026`. No acervo ([`DOC-001`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-001-Edital-006-2026.txt) e [`DOC-007`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-007-Edital-Retificador-07-2026-Ajuste-Calendario.txt)), o cronograma foi saneado mantendo a vigência final consolidada. |
| **Edital 006/2026**<br>Item 11.1 (pág. 12) | **Erro tipográfico evidente de ano:**<br>Consta *"entre os dias 11/06/2026 e 24/06/206"*. | Data corrompida que poderia levar o modelo a extrair ano inválido. | No [`DOC-SECITECI-001`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-001-Edital-006-2026.txt), o texto foi adaptado com o ano regular `2026`. |
| **Edital 006/2026**<br>Subitem de 11.1 (pág. 12) | **Numeração quebrada:**<br>Após o item `11.1`, o subitem seguinte vem numerado como `10.2` em vez de `11.1.1` ou `11.2`. | Quebra na hierarquia de artigos/seções na indexação do chunk. | Saneado na formatação textual do acervo, mantendo a regra sob a seção de vagas remanescentes. |
| **Edital 006/2026**<br>Item 11.3.1 alínea "c" (pág. 13) | **Data impossível para 4ª chamada:**<br>Informa que as matrículas da 4ª chamada seriam publicadas em `11/06/2026` (mesmo dia da 1ª chamada). | Impossibilidade temporal no processo de chamadas sucessivas. | Saneado e substituído pelo cronograma oficial consolidado no Retificador 05 / [`DOC-SECITECI-007`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-007-Edital-Retificador-07-2026-Ajuste-Calendario.txt). |
| **Edital 006/2026**<br>Anexo II (Autodeclaração Indígena, pág. 16) | **Anacronismo por reaproveitamento de minuta:**<br>Cabeçalho cita *"EDITAL Nº 06/2025 - SEGUNDO SEMESTRE DE 2025"* e data final *"____ de ________ 2024"*. | Discrepância de ano entre o corpo do edital (2026) e o anexo formal. | O RAG possui guardrail temporal contra anos não cobertos e o acervo padroniza a vigência do ano letivo de 2026. |
| **Retificador 05**<br>Data de assinatura (pág. 3) | **Data em branco:**<br>Consta *"Cuiabá/MT, ____ de junho de 2026"*. | Ausência de data formal de expedição no rodapé do documento. | A data de vigência foi associada à publicação do ato e consolidada formalmente no [`DOC-SECITECI-007`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-007-Edital-Retificador-07-2026-Ajuste-Calendario.txt). |

---

## 3. Inconsistências Identificadas nas Solicitações dos Cidadãos

| Solicitação | Dado Informado pelo Cidadão | Realidade no Acervo Normativo | Tratamento no Pipeline (NLP + RAG + Minuta) |
| :--- | :--- | :--- | :--- |
| **SOL-01 / entrada_texto.txt**<br>(Marcos Vinícius) | Carga horária: `1200h`<br>Início: `01/02/2027` | *Téc. em Enfermagem* em Cuiabá possui `1600h` e início em `21/07/2026`. | **Validação e Separação:** O Pydantic (`RF14`) extrai literalmente o que o cidadão digitou sem inventar dados faltantes; a minuta fundamentada (`RF19`) confronta a declaração do solicitante com a norma do acervo, esclarecendo a carga horária real e o calendário vigente. |
| **SOL-04**<br>(Juliana Mendes) | Solicita auxílios informando renda per capita de R$ 800,00, sem anexar contracheques ou residência. | A Instrução Normativa ([`DOC-005`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-005-Instrucao-Normativa-Renda.txt)) exige rol exaustivo de 5 tipos documentais. | A triagem classifica como `Assistência Estudantil`, o RAG cita os documentos exigidos e a minuta orienta a complementação antes de indeferimento sumário. |
| **SOL-05**<br>(João) | Mensagem incompleta ("Gostaria de saber da minha vaga", sem sobrenome, CPF ou curso). | Requisitos obrigatórios ausentes. | Classificado como categoria `"revisão"`, gerando pendência de interpelação e bloqueio de envio automático. |
| **SOL-06**<br>(Carla Ribeiro) | Solicitação ambígua confundindo polo de sorteio (Barra do Garças) e polo de residência (Cuiabá). | Edital veda transferência sumária entre turmas/polos distintos. | Sinalizado com `necessidade_revisao = True` para deliberação de atendente humano. |

---

## 4. Evolução do Acervo e o Edital Retificador nº 07 (`DOC-SECITECI-007`)

### O Problema Histórico:
1. No documento adaptado inicial [`DOC-SECITECI-002`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-002-Retificador-03-Cronograma.pdf), a redação do Art. 2º mencionava envio de vídeo de heteroidentificação para *"pretos, pardos e indígenas"*, enquanto a regra geral e o Retificador 04 exigem vídeo `.mp4` **exclusivamente para candidatos negros (pretos ou pardos - L1)** (indígenas comprovam por declaração de liderança na matrícula).
2. O [`DOC-SECITECI-003`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-003-Retificador-06-Calendario-Pontual.txt) citava nominalmente apenas 4 turmas prorrogadas, enquanto o Retificador 06 original da SECITECI abrangeu **14 ofertas descentralizadas**.

### A Solução Administrativa Adotada:
Em respeito ao princípio da **Imutabilidade e Segurança Jurídica dos Atos Administrativos**, decidiu-se não reescrever o passado nem alterar retroativamente os documentos base `DOC-001`, `DOC-002` e `DOC-003`. 

Em vez disso, a equipe emitiu formalmente o **Edital Retificador nº 07/2026/SECITECI-MT ([`DOC-SECITECI-007`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-007-Edital-Retificador-07-2026-Ajuste-Calendario.txt))**, que:
- **Possui precedência temporal expressa** sobre cronogramas anteriores;
- Consolida as **14 localidades/cursos descentralizados** com início em `05/10/2026`;
- Ratifica `21/07/2026` para as turmas da sede (Cuiabá);
- Esclarece formalmente que candidatos indígenas (`L3`) e PcD (`L4`) não enviam vídeo de heteroidentificação, cabendo comprovação exclusivamente documental na matrícula presencial.

---

## 5. Conflito Normativo Deliberado para Avaliação do RAG (`P8` / `T10`)

Para cumprir o requisito obrigatório de **detecção de fontes conflitantes sem invenção de prazos**:
- **[`DOC-SECITECI-004`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-004-Regulamento-Assistencia-Estudantil.pdf) (Portaria Normativa 042/2026 - Norma Superior):** Art. 7º exige entrega da comprovação de frequência até o **5º dia útil de cada mês** (85% de presença).
- **[`DOC-SECITECI-006`](file:///c:/Users/branco/Documents/GitHub/desafio-ficdev-02-ia/dados/acervo/DOC-SECITECI-006-Comunicado-Contraditorio-Prazos.pdf) (Comunicado Interno 014/2026 - Norma Setorial Local):** Item 1 flexibiliza a entrega até o **dia 20 de cada mês** (70% de presença).

**Comportamento do RAG:** O sistema reconhece a divergência normativa entre o regulamento geral e o comunicado setorial, abstém-se de tomar partido automaticamente, rotula o status como `conflito_de_fontes` e submete o caso com citações de ambos os textos para decisão do operador humano (`Human-in-the-Loop`).

