"""Edge real + FastAPI temporário. Provedores simulados; sem APIs ou dados reais.

Executar manualmente: python -m testes.validar_navegador_local --executar
Requer Edge Windows e websockets (incluído em uvicorn[standard]). Não instala nada.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import wave


def executar():
    import requests
    import uvicorn
    from websockets.sync.client import connect
    import src
    from src import main
    from src.audit import AuditLogger
    from src.llm_client import LLMResponse

    raiz = Path(tempfile.mkdtemp(prefix="ficdev_browser_teste_"))
    for pasta in ["dados/originais", "dados/gabaritos", "src/web"]:
        shutil.copytree(src.BASE_DIR / pasta, raiz / pasta)
    shutil.copy2(src.BASE_DIR / "config.json", raiz / "config.json")
    src.BASE_DIR = main.BASE_DIR = raiz
    main.audit_logger = AuditLogger(str(raiz / "logs"))
    main.audio_processor.audios_dir = raiz / "resultados/audios"
    main.image_generator.output_dir = raiz / "resultados/imagens"
    for rota in main.app.routes:
        if getattr(rota, "path", "") == "/arquivos":
            rota.app.directory = str(raiz)
            rota.app.all_directories = [str(raiz)]
    payload = json.dumps({"extracao": {"solicitante": "Pessoa Fictícia", "protocolo": "inválido"},
                          "minuta_institucional": "Minuta fictícia. Protocolo inválido. Informação não localizado."})
    main.llm_client.generate = lambda *a, **kw: LLMResponse(payload, "modelo-teste", "mock-browser", .01, 1, 1, 2, None, "success")
    os.environ["TTS_PROVIDER"] = "sapi5"  # Somente no processo de teste.
    def voz(texto, caminho):
        with wave.open(caminho, "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 800)
        return "Voz simulada no teste"
    main.audio_processor._sintetizar_sapi5 = voz
    main.audio_processor.processar_com_auditoria = lambda *a: {
        "sucesso": True, "metadados": {"duracao_segundos": 1, "modelo_stt": "small"},
        "transcricao_bruta": "Áudio fictício", "transcricao_revisada": "Áudio fictício",
        "comparacao_gabarito": {"acuracia_entidades": "0/6"}}
    main.vision_processor.processar_com_auditoria = lambda *a: {
        "sucesso": True, "arquivo_analisado": "teste.pdf", "texto_corrigido": "OCR fictício",
        "comparacao_gabarito": {"taxa_acuracia_percentual": "0.0%"}, "trechos_incertos_ou_ilegiveis": []}
    def bloquear(*a, **kw):
        raise AssertionError("Cloudflare proibida no teste de navegador")
    main.image_generator._gerar_ilustracao_ia = bloquear
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); porta = sock.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(main.app, log_level="critical", access_log=False))
    thread = threading.Thread(target=servidor.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    for _ in range(200):
        if servidor.started: break
        time.sleep(.05)
    for caminho in ["/", "/static/app.js", "/api/config"]:
        resposta_http = requests.get(f"http://127.0.0.1:{porta}{caminho}", timeout=5)
        assert resposta_http.status_code == 200, (caminho, resposta_http.status_code)
    perfil = raiz / "perfil"
    exe = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    browser = None
    try:
        browser = subprocess.Popen([str(exe), "--headless", "--disable-gpu", "--no-first-run",
            "--disable-extensions", "--disable-background-networking", "--no-proxy-server",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1", f"--user-data-dir={perfil}", f"http://127.0.0.1:{porta}/"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(200):
            if (perfil / "DevToolsActivePort").exists(): break
            time.sleep(.05)
        debug = int((perfil / "DevToolsActivePort").read_text().splitlines()[0])
        alvos = requests.get(f"http://127.0.0.1:{debug}/json/list", timeout=5).json()
        alvo = next(a for a in alvos if a.get("type") == "page")
        with connect(alvo["webSocketDebuggerUrl"], proxy=None, max_size=8000000) as ws:
            contador = 0
            def cdp(metodo, parametros=None):
                nonlocal contador
                contador += 1; identificador = contador
                ws.send(json.dumps({"id": identificador, "method": metodo, "params": parametros or {}}))
                while True:
                    resposta = json.loads(ws.recv(timeout=20))
                    if resposta.get("id") == identificador:
                        assert "error" not in resposta, resposta.get("error")
                        return resposta.get("result", {})
            def js(expressao):
                r = cdp("Runtime.evaluate", {"expression": expressao, "awaitPromise": True, "returnByValue": True})
                assert "exceptionDetails" not in r, r.get("exceptionDetails")
                return r.get("result", {}).get("value")
            def esperar(condicao):
                # A navegação troca o contexto JS; não deixar uma Promise presa
                # no about:blank ou em uma extensão de segundo plano.
                for _ in range(200):
                    try:
                        if js("Boolean(" + condicao + ")"): return True
                    except AssertionError:
                        pass
                    time.sleep(.05)
                raise AssertionError("Tempo esgotado no teste: " + condicao)
            def clicar(id, condicao):
                js("document.getElementById(" + json.dumps(id) + ").click()")
                return esperar(condicao)
            cdp("Page.enable")
            cdp("Network.enable")
            cdp("Network.setBlockedURLs", {"urls": ["*fonts.googleapis.com*", "*fonts.gstatic.com*"]})
            # A página inicial é aberta pelo próprio navegador, antes de anexar CDP.
            esperar("document.getElementById('badge-api-mode')?.textContent.includes('Texto:')")
            js("window.alertasTeste=[];window.alert=m=>alertasTeste.push(m);window.open=url=>{window.pdfTeste=url;};")
            for largura in [390, 1366]:
                cdp("Emulation.setDeviceMetricsOverride", {"width": largura, "height": 1000, "deviceScaleFactor": 1, "mobile": largura < 600})
                medidas = js("Array.from(document.querySelectorAll('.nav-tab')).map(t=>{t.click();return {aba:t.dataset.tab,largura:document.documentElement.scrollWidth,viewport:innerWidth};})")
                print("LAYOUT", json.dumps(medidas), flush=True)
                assert all(m["largura"] <= largura + 1 for m in medidas), "Overflow horizontal"
            js("document.querySelector('[data-tab=tab-atendimento]').click();document.getElementById('caso-predefinido').value='personalizado';document.getElementById('input-texto-solicitacao').value='Pedido fictício';")
            clicar("btn-processar-solicitacao", "document.getElementById('editor-minuta').value.includes('Minuta fictícia') && !document.getElementById('btn-processar-solicitacao').disabled")
            assert js("document.getElementById('btn-gerar-tts').disabled")
            js("document.getElementById('justificativa-revisao').value='Conferência automatizada de dados fictícios';")
            clicar("btn-aprovar-minuta", "!document.getElementById('btn-gerar-tts').disabled")
            clicar("btn-gerar-tts", "document.getElementById('tts-audio-container').style.display==='flex' && !document.getElementById('btn-gerar-tts').disabled")
            audio = js("document.getElementById('tts-audio-player').getAttribute('src')")
            assert requests.get(f"http://127.0.0.1:{porta}" + audio, timeout=5).status_code == 200
            clicar("btn-exportar-pdf", "!!window.pdfTeste")
            assert requests.get(f"http://127.0.0.1:{porta}" + js("window.pdfTeste"), timeout=5).status_code == 200
            js("document.getElementById('btn-ir-conferencia').click()")
            assert js("document.getElementById('subtab-conferencia').classList.contains('active')")
            for filtro in ["todos", "divergentes", "pendencias"]:
                js("document.querySelector('[data-filter=" + filtro + "]').click()")
                if filtro == "pendencias":
                    assert js("Array.from(document.querySelectorAll('#tabela-conferencia-body tr:not(#tr-empty-filter)')).filter(r=>r.style.display!=='none').every(r=>r.dataset.status==='PENDENCIA')")
            js("document.querySelector('[data-filter=todos]').click();window.prompt=()=> '2099-123456';document.querySelector('.btn-corrigir-inline').click()")
            assert js("document.getElementById('editor-minuta').value.includes('2099-123456') && document.getElementById('btn-gerar-tts').disabled")
            for subtab in ["subtab-json", "subtab-metricas", "subtab-minuta"]:
                js("document.querySelector('[data-subtab=" + subtab + "]').click()")
                assert js("document.getElementById('" + subtab + "').classList.contains('active')")
            js("let e=document.getElementById('editor-minuta');e.value+=' Alterada.';e.dispatchEvent(new Event('input'));")
            assert js("document.getElementById('btn-gerar-tts').disabled")
            clicar("btn-corrigir-minuta", "document.getElementById('badge-status-revisao').textContent.includes('CORRIGIDO')")
            clicar("btn-rejeitar-minuta", "document.getElementById('badge-status-revisao').textContent.includes('REJEITADO')")
            js("document.querySelector('[data-tab=tab-experimento]').click()")
            clicar("btn-rodar-experimento", "document.getElementById('exp-out-c').textContent.includes('minuta_institucional') && !document.getElementById('btn-rodar-experimento').disabled")
            js("document.querySelector('[data-tab=tab-multimodal]').click()")
            clicar("btn-processar-audio", "document.getElementById('resultado-audio-stt').textContent.includes('Áudio fictício')")
            clicar("btn-processar-visao", "document.getElementById('resultado-visao-ocr').textContent.includes('OCR fictício')")
            assert js("document.getElementById('btn-gerar-imagem-peca').disabled")
            main.llm_client.generate = lambda *a, **kw: LLMResponse("JSON inválido", "modelo", "mock", .01, 1, 1, 2, None, "success")
            js("document.querySelector('[data-tab=tab-atendimento]').click();window.alertasTeste=[];")
            clicar("btn-processar-solicitacao", "alertasTeste.some(m=>m.includes('HTTP 502') && m.includes('JSON válido'))")
            esperar("!document.getElementById('btn-processar-solicitacao').disabled")
            assert js("document.getElementById('btn-aprovar-minuta').disabled && document.getElementById('btn-gerar-tts').disabled")
            cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 1000, "deviceScaleFactor": 1, "mobile": True})
            captura = cdp("Page.captureScreenshot", {"format": "png"})
            (raiz / "mobile.png").write_bytes(base64.b64decode(captura["data"]))
            print("BROWSER_OK: abas, texto, PDF/WAV HTTP, revisão/hash, RF02/06/08 com mocks, RF10 bloqueado e erro 502. Evidência:", raiz / "mobile.png", flush=True)
            cdp("Browser.close")
    finally:
        if browser and browser.poll() is None: browser.terminate()
        if browser:
            try: browser.wait(timeout=5)
            except subprocess.TimeoutExpired: browser.kill()
        servidor.should_exit = True; thread.join(timeout=5); sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executar", action="store_true")
    if not parser.parse_args().executar: parser.error("Use --executar explicitamente; testes não iniciam navegador automaticamente.")
    executar()
