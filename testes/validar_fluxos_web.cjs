// Executa app.js real em DOM mínimo: transportes simulados, sem consumir APIs.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../src/web/index.html'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../src/web/app.js'), 'utf8');
const elementos = new Map(), todos = [], alertas = [], chamadas = [], rotas = new Map();
function elemento(attrs) {
  const classes = new Set((attrs.class || '').split(/\s+/));
  const e = {value:'', textContent:'', innerHTML:'', style:{}, disabled: 'disabled' in attrs,
    listeners:{}, dataset:{}, className:attrs.class || '',
    getAttribute:n=>attrs[n] ?? null, addEventListener(n, fn){this.listeners[n]=fn;},
    classList:{add:n=>classes.add(n), remove:n=>classes.delete(n), contains:n=>classes.has(n)},
    querySelectorAll:()=>[], querySelector:()=>({textContent:''}),
    play:()=>Promise.resolve(), click(){return this.listeners.click?.();}};
  for (const [k,v] of Object.entries(attrs)) if(k.startsWith('data-')) e.dataset[k.slice(5)]=v;
  todos.push(e); if(attrs.id) elementos.set(attrs.id,e); return e;
}
for(const m of html.matchAll(/<[a-z][a-z0-9-]*\b([^>]*)>/gi)) {
  const attrs={}; for(const a of m[1].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]]=a[2] || '';
  elemento(attrs);
}
const el=id=>elementos.get(id) || null;
const corpo={sucesso:true,id_execucao:'EXEC_UI',extracao:{protocolo:'2099-123456',solicitante:'Pessoa fictícia'},
  minuta_institucional:'Minuta fictícia para revisão',url_pdf:'/arquivos/resultados/minutas/ui.pdf',
  metricas:{duracao_segundos:0.1,total_tokens:10,custo_usd:null},
  conformidade_formato:{erros_encontrados:[],comparativo_campos:[],status_qualidade:'Revisão humana pendente'}};
const config={texto:{provedor:'openrouter',modelo:'google/gemini-3.8-flash',habilitado:true},
  stt:{provedor:'local',modelo:'small'},tts:{provedor:'sapi5'},rf10_administrativo_habilitado:false};
function definir(url,body,status=200){rotas.set(url,()=>({body,status}));}
definir('/api/config',config);
definir('/api/processar/texto',corpo);
definir('/api/revisao/decisao',{sucesso:true});
definir('/api/sintetizar/audio',{sucesso:true,url_audio:'/arquivos/resultados/audios/ui.wav'});
definir('/api/minuta/gerar_pdf',{sucesso:true,url_pdf:'/arquivos/resultados/minutas/ui.pdf'});
definir('/api/lgpd/relatorio',{titulo:'LGPD',matriz_de_dados:{},declaracao_dados_ficticios:'Dados de teste'});
definir('/api/logs',[{id_execucao:'EXEC_UI',modalidade:'texto',modelo:'modelo',timestamp:new Date().toISOString(),
  decisao_humana:{status:'pendente_revisao'},decisao_humana_atual:{status:'APROVADO',justificativa:'<img src=x onerror=alert(1)>'}}]);
const contexto={console,Date,JSON,String,Number,Map,alert:m=>alertas.push(m),
  window:{prompt:()=>null,open(){}},document:{
    addEventListener(n,fn){if(n==='DOMContentLoaded') fn();},getElementById:el,
    querySelectorAll(s){
      if(s==='.nav-tab' || s==='.sub-tab' || s==='.tab-pane' || s==='.subtab-pane') return todos.filter(e=>e.classList.contains(s.slice(1)));
      if(s==='.conferencia-filters .btn-filter') return todos.filter(e=>e.classList.contains('btn-filter'));
      return [];
    }},
  fetch:async(url,op={})=>{
    chamadas.push({url,...op});
    const handler=rotas.get(url);
    const r=handler ? await handler() : {body:{conteudo:'Entrada fictícia'},status:200};
    return {status:r.status,ok:r.status<400,json:async()=>{if(r.nonJson)throw Error('HTML');return r.body;}};
  }};
vm.runInNewContext(script,contexto);
const esperar=()=>new Promise(resolve=>setImmediate(resolve));
const clicar=async id=>{await el(id).listeners.click(); await esperar();};
(async()=>{
  await esperar();
  assert.match(el('badge-api-mode').textContent,/openrouter.*gemini/);
  assert.equal(el('btn-gerar-imagem-peca').disabled,true);
  assert.equal(el('btn-gerar-tts').disabled,true);
  for(const e of todos.filter(e=>e.classList.contains('nav-tab'))) {
    await e.listeners.click(); await esperar();
    assert.equal(el(e.getAttribute('data-tab')).classList.contains('active'),true);
  }
  for(const e of todos.filter(e=>e.classList.contains('sub-tab'))) {
    await e.listeners.click(); assert.equal(el(e.getAttribute('data-subtab')).classList.contains('active'),true);
  }
  for(const e of todos.filter(e=>e.classList.contains('btn-filter'))) e.listeners.click();
  await clicar('btn-atualizar-logs');
  assert.ok(el('audit-logs-container').innerHTML.includes('APROVADO'));
  assert.ok(!el('audit-logs-container').innerHTML.includes('<img'));
  el('input-texto-solicitacao').value='Texto fictício';
  let soltar;
  rotas.set('/api/processar/texto',()=>new Promise(resolve=>{soltar=()=>resolve({body:corpo,status:200});}));
  const pendente=el('btn-processar-solicitacao').listeners.click();
  assert.equal(el('btn-processar-solicitacao').disabled,true);
  assert.equal(el('btn-aprovar-minuta').disabled,true);
  soltar(); await pendente;
  definir('/api/processar/texto',corpo);
  assert.equal(el('editor-minuta').value,corpo.minuta_institucional);
  assert.equal(el('btn-gerar-tts').disabled,true);
  await clicar('btn-exportar-pdf');
  const pdf=JSON.parse(chamadas.find(c=>c.url==='/api/minuta/gerar_pdf').body);
  assert.equal(pdf.solicitante,'Pessoa fictícia'); assert.equal(pdf.protocolo,'2099-123456');
  el('justificativa-revisao').value='Conferido na fonte';
  await clicar('btn-aprovar-minuta');
  const revisao=JSON.parse(chamadas.find(c=>c.url==='/api/revisao/decisao').body);
  assert.equal(revisao.id_execucao,'EXEC_UI'); assert.equal(revisao.texto_final,corpo.minuta_institucional);
  assert.equal(el('btn-gerar-tts').disabled,false);
  const minutaAprovada = el('editor-minuta').value;
  const jsonAprovado = el('json-extracao-view').textContent;
  await clicar('btn-aplicar-mascaras-todas');
  await clicar('btn-aplicar-digitos-todas');
  assert.equal(el('editor-minuta').value, minutaAprovada);
  assert.equal(el('json-extracao-view').textContent, jsonAprovado);
  assert.equal(el('btn-gerar-tts').disabled,false);
  await clicar('btn-gerar-tts'); assert.ok(el('tts-audio-player').src.includes('ui.wav'));
  el('editor-minuta').value+=' alterada'; el('editor-minuta').listeners.input();
  assert.equal(el('btn-gerar-tts').disabled,true);
  await clicar('btn-corrigir-minuta'); assert.equal(el('btn-gerar-tts').disabled,true);
  await clicar('btn-rejeitar-minuta'); assert.equal(el('btn-gerar-tts').disabled,true);
  definir('/api/revisao/decisao',{detail:'Execução não encontrada.'},404);
  await clicar('btn-aprovar-minuta'); assert.match(alertas.at(-1),/HTTP 404.*Execução/);
  definir('/api/processar/audio',{sucesso:true,metadados:{duracao_segundos:1,modelo_stt:'small'},
    transcricao_bruta:'<script>x</script>',transcricao_revisada:'Revisar',comparacao_gabarito:{acuracia_entidades:'3/6'}});
  await clicar('btn-processar-audio'); assert.ok(!el('resultado-audio-stt').innerHTML.includes('<script>'));
  definir('/api/processar/audio',{sucesso:false,erro:'Modelo local indisponível.'});
  await clicar('btn-processar-audio'); assert.match(alertas.at(-1),/Modelo local/);
  assert.equal(el('btn-processar-audio').disabled,false);
  definir('/api/processar/visao',{sucesso:true,arquivo_analisado:'oficial.pdf',texto_corrigido:'OCR',
    comparacao_gabarito:{taxa_acuracia_percentual:'0.0%'},trechos_incertos_ou_ilegiveis:['<img src=x>']});
  await clicar('btn-processar-visao'); assert.ok(!el('resultado-visao-ocr').innerHTML.includes('<img'));
  definir('/api/processar/visao',{detail:'PDF inválido'},422); await clicar('btn-processar-visao');
  assert.equal(el('btn-processar-visao').disabled,false); assert.match(alertas.at(-1),/HTTP 422/);
  const resultados=Object.fromEntries(['a','b','c'].map(t=>['prompt_'+t,{texto:'Prompt '+t,duracao_segundos:.1}]));
  definir('/api/experimento/prompts',{sucesso:true,resultados});
  await clicar('btn-rodar-experimento'); assert.equal(el('exp-out-c').textContent,'Prompt c');
  definir('/api/experimento/prompts',{detail:'Limite atingido'},503);
  await clicar('btn-rodar-experimento'); assert.match(alertas.at(-1),/HTTP 503.*Limite/);
  assert.equal(el('btn-rodar-experimento').disabled,false);
  definir('/api/gerar/imagem',{detail:'RF10 desabilitado até autenticação real.'},503);
  await clicar('btn-gerar-imagem-peca'); assert.match(alertas.at(-1),/HTTP 503.*RF10/);
  assert.equal(el('btn-gerar-imagem-peca').disabled,true);
  // Reproduz a antiga "Falha desconhecida": FastAPI usa detail, não erro.
  definir('/api/processar/texto',{detail:'Resposta do modelo sem JSON válido; nenhuma minuta foi produzida.'},502);
  await clicar('btn-processar-solicitacao'); assert.match(alertas.at(-1),/HTTP 502.*JSON válido/);
  assert.equal(el('btn-processar-solicitacao').disabled,false);
  assert.equal(el('btn-aprovar-minuta').disabled,true);
  assert.equal(el('btn-gerar-tts').disabled,true);
  definir('/api/processar/texto',{detail:[{loc:['body','texto'],msg:'Campo obrigatório',input:'SEGREDO_NAO_EXIBIR'}]},422);
  await clicar('btn-processar-solicitacao'); assert.match(alertas.at(-1),/body.texto/);
  assert.ok(!alertas.at(-1).includes('SEGREDO_NAO_EXIBIR'));
  rotas.set('/api/processar/texto',()=>({status:500,nonJson:true}));
  await clicar('btn-processar-solicitacao'); assert.match(alertas.at(-1),/HTTP 500.*JSON/);
  rotas.set('/api/processar/texto',()=>{throw Error('credencial_privada');});
  await clicar('btn-processar-solicitacao'); assert.match(alertas.at(-1),/servidor está ativo/);
  assert.ok(!alertas.at(-1).includes('credencial_privada'));
  for(const caso of ['texto_original','prompt_injection','audio_transcricao','visao_documento','personalizado']) {
    el('caso-predefinido').value=caso;
    await el('caso-predefinido').listeners.change({target:{value:caso}});
    assert.equal(el('btn-processar-solicitacao').disabled,false);
  }
  await clicar('btn-limpar-texto'); assert.equal(el('input-texto-solicitacao').value,'');
  console.log('DOM completo: abas, filtros, texto, PDF, revisão, TTS, RF02/06/08, RF10 bloqueado, auditoria e erros HTTP OK.');
})().catch(e=>{console.error(e);process.exitCode=1;});
