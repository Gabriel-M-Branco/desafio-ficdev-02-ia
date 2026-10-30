# Correções após auditoria do Desafio 02

Esta é a referência atual para as correções. Relatórios e métricas anteriores
descrevem execuções históricas; não demonstram aprovação da versão atual.

## Comportamento e limites

- Revisão: os quatro estados da interface são persistidos, com operador,
  justificativa e horário. O status legado é mantido para compatibilidade com TTS;
  o campo `estado` preserva pendente/aprovada/rejeitada/revisar. Falha de gravação
  não confirma a decisão na interface. Aprovação continua vinculada ao hash do
  texto exato, mesmo quando o texto mostrado no log é mascarado.
- RAG local: seleciona passagens literais para as intenções documentadas no
  acervo. Considera ano, curso/localidade e entidade de programa. Não equivale a
  um modelo semântico geral. Perguntas não cobertas são encaminhadas à revisão.
- RAG remoto: solicita seleção estruturada de passagens, valida ID e texto literal
  e retém saídas inválidas. Não autoriza paráfrases livres como fatos verificados.
  As chamadas reais e a qualidade de provedores externos não foram certificadas.
- Simulação: a segunda configuração continua explicitamente identificada; sua
  resposta institucional usa seleção extrativa local, sem alegar qualidade de LLM.
- Fontes: DOC-001/002/003/007 são adaptações didáticas e retificações; DOC-004/005/006 são fictícios.
  As citações mostram natureza, origem, página da adaptação e identificador do
  trecho. A adaptação não é apresentada como cópia integral do original.
- DOC-002 separa referências às Retificações 03, 04 e 05, corrige calendário e
  escopo da heteroidentificação. DOC-003 relaciona as 14 ofertas da Retificação 06.
- NLP: o resumo extrativo preserva o pedido. Início, carga horária e eixo não são
  preenchidos por suposição. Os gabaritos de ausências foram conferidos novamente.
- Métricas: recuperação exige trecho de referência; resposta exige fatos esperados
  e passagens ligadas às próprias fontes. A/B usa o mesmo vocabulário e IDF.
  A seleção RAG amplia candidatos antes de escolher os trechos citados; isso é
  distinto da medição de recuperação top-3 de RF18.
- T11 inclui persistência real, e há AppTest do Streamlit para aprovação, rejeição,
  revisão e falha de gravação. T15 tenta OCR local real até minuta/revisão; registra
  pendência quando não há motor ou texto útil. Não converte indisponibilidade em
  aprovação. Ensaios automatizados de decisão são identificados como testes.

## Reproduzir sem contaminar evidências

```powershell
python -B testes/executar_isolado.py testes/ -v
python -B testes/executar_isolado.py --metricas
```

O executor copia o projeto para uma pasta temporária e não copia `.env`. As
requisições HTTP da suíte são bloqueadas. Para guardar a matriz medida e atualizar
o relatório exibido pelo painel, use `--metricas --salvar-evidencia`.

O arquivo `evidencias/validacao_d02.json` contém os resultados atuais quando essa
opção é executada. A versão anterior do acervo/índice/gabarito RAG/relatório foi
preservada em `evidencias/antes_correcao_d02.zip`, com hashes dos originais.

## Índice e revisão manual

Instale `requirements.txt` no ambiente utilizado para executar a aplicação.
Recrie explicitamente o índice após modificar o acervo:

```powershell
python -m src.ingestion
python -m src.main
```

Também é possível selecionar documentos e recriar o índice no módulo 9. Trocar o
provedor no módulo 6 não recria o índice.

No módulo 6, use geração local, confira os trechos e a natureza da fonte. No fluxo
integrado, informe uma solicitação como “Nome: Ana Silva. Gostaria de saber a data
de início do curso Técnico em Agropecuária em Mimoso.” Registre operador,
justificativa e decisão. Confira a persistência no módulo 5. Teste também uma
pergunta sobre 2027, vídeo para indígenas e prazo de frequência do auxílio.

## Retenção e exclusão no protótipo

Os originais são imutáveis. Fontes adaptadas e evidências históricas são retidas
para revisão da avaliação; não há expiração automática. Excluir no módulo 9 remove
chunks/vetores da recuperação ativa e registra o evento. Não apaga documentos de
origem, minutas ou logs históricos. Recriar o índice pode reincluir uma fonte ainda
selecionada. Exclusão completa de fontes e resultados derivados continua parcial
e exige procedimento específico; não se anuncia expurgo integral.

Logs e dados originais/processados não são downloads públicos pela rota genérica.
Novos logs e decisões são mascarados, assim como a leitura dos registros antigos.
Os registros antigos em disco são preservados; não foram reescritos em massa.
A aplicação permanece um protótipo local; isso não certifica autenticação de
produção nem autoriza exposição pública de minutas com dados pessoais.
