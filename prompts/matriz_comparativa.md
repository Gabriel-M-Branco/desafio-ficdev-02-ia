# Matriz Comparativa do Experimento de Engenharia de Prompts (RF02)

| Critério de Avaliação | Prompt A (Zero-Shot Curto) | Prompt B (Estruturado Manualmente) | Prompt C (Metaprompt / Produção) |
|---|---|---|---|
| **Fidelidade ao Contexto** | Média (resposta informal, omite requisitos chave) | Alta (segue o tom institucional e campos solicitados) | Estrita / Excelente (100% de aderência documental) |
| **Dados Inventados (Alucinação)** | Risco Alto (tende a inferir datas ou dados não informados) | Baixo Risco (orientado a não inventar) | Alucinação Zero (regra explícita de 'não localizado') |
| **Formato de Saída** | Texto livre corrido sem padronização | Texto estruturado com marcadores e campos | JSON Estruturado validável + Minuta Oficial timbrada |
| **Tom e Adequação Institucional** | Informal / Não padronizado | Formal / Padrão GOV.MT | Oficial Padrão GOV.MT com fundamentação técnica |
| **Tratamento de Lacunas** | Omissão de campos ausentes | Inclusão parcial de aviso de dados pendentes | Marcação obrigatória de 'não localizado' para cada campo |
| **Blindagem contra Prompt Injection** | Inexistente / Vulnerável a comandos inseridos | Parcial (instruções gerais) | Robusta com envelope XML `<conteudo_nao_confiavel>` |
| **Tempo até Resultado Utilizável** | 16.04s (2200 tokens) | 17.22s (3021 tokens) | 15.76s (4087 tokens) |

## Justificativa da Seleção do Prompt Incorporado
O **Prompt C (Metaprompting com Blindagem de Produção)** foi selecionado como o prompt oficial incorporado ao sistema por três motivos determinantes:
1. **Segurança contra Injeção:** Isola comandos de dados externos através de tags delimitadoras `<conteudo_nao_confiavel>`.
2. **Alucinação Zero:** Aplica rigorosamente o termo `'não localizado'` para qualquer campo ausente, mitigando riscos de invenção jurídica ou administrativa.
3. **Contrato de Dados:** Produz JSON estrito e validável, compatível com a verificação automatizada de esquemas e com o despacho oficial timbrado do GOV.MT.