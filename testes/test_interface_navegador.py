"""Verificação opcional com Edge/Playwright já instalados, em cópia isolada.

PowerShell: $env:FICDEV_BROWSER_TEST='1'
python -B testes/executar_isolado.py testes/test_interface_navegador.py -v
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("FICDEV_TEST_COPY") != "1" or os.getenv("FICDEV_BROWSER_TEST") != "1",
    reason="Requer cópia isolada e FICDEV_BROWSER_TEST=1; usa Edge e Playwright locais.",
)


def test_navegacao_matriz_e_revisao_no_navegador():
    from playwright.sync_api import sync_playwright, expect

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        porta = sock.getsockname()[1]
    ambiente = os.environ.copy()
    ambiente["PYTHONPATH"] = os.pathsep.join(sys.path)
    with tempfile.TemporaryFile() as log:
        servidor = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "src/app.py",
             "--server.headless=true", f"--server.port={porta}",
             "--server.address=127.0.0.1", "--browser.gatherUsageStats=false"],
            env=ambiente, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            url = f"http://127.0.0.1:{porta}"
            for _ in range(120):
                try:
                    with urlopen(url + "/_stcore/health", timeout=1) as resposta:
                        if resposta.status == 200:
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                pytest.fail("Streamlit não iniciou para o teste de navegador.")

            with sync_playwright() as pw:
                navegador = pw.chromium.launch(channel="msedge", headless=True)
                try:
                    pagina = navegador.new_page(viewport={"width": 1440, "height": 1000})
                    erros = []
                    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
                    pagina.goto(url)
                    menu = pagina.get_by_role("radiogroup").first
                    matriz = "10. Matriz de testes"
                    rag = "6. Assistente documental"
                    sentimentos = "8. Painel de sentimentos"
                    for largura in (1440, 960):
                        pagina.set_viewport_size({"width": largura, "height": 1000})
                        for modulo in (matriz, rag, sentimentos, matriz):
                            menu.get_by_text(modulo, exact=True).click()
                            expect(pagina.get_by_role("heading", level=3).first).to_contain_text(modulo.split(".")[0] + ".")
                        expect(pagina.get_by_text("Origem dos dados", exact=True)).to_be_visible()
                        expect(pagina.get_by_text("Duração da bateria", exact=True)).to_be_visible()
                        for metrica in pagina.get_by_test_id("stMetricValue").all():
                            assert metrica.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
                        assert menu.get_by_role("radio").count() == 10
                        if os.getenv("FICDEV_UI_SCREENSHOT_DIR"):
                            pagina.screenshot(path=os.path.join(os.environ["FICDEV_UI_SCREENSHOT_DIR"], f"ficdev-menu-{largura}.png"))

                    menu.get_by_text("7. Triagem e ficha", exact=True).click()
                    texto = pagina.get_by_role("textbox", name="Texto da Manifestação:", exact=True)
                    protocolo = pagina.get_by_role("textbox", name="Protocolo Externo (opcional):", exact=True)
                    expect(protocolo).to_have_value("2026-000142")
                    # Primeiro processe o exemplo e mantenha a extração aberta,
                    # como na sessão em que o usuário encontrou o resíduo.
                    pagina.get_by_role("button", name="Processar Ficha Pydantic", exact=True).click()
                    pagina.get_by_text("Dados extraídos e triagem — RF14 / RF15", exact=True).click()
                    expect(pagina.get_by_test_id("stJson").first).to_contain_text("2026-000142")
                    # Substituição direta, sem um rerun intermediário forçado
                    # por Tab: reproduz a edição e o clique usados manualmente.
                    texto.fill("Solicito apenas Auxílio Transporte.")
                    protocolo.fill("")
                    pagina.get_by_role("button", name="Processar Ficha Pydantic", exact=True).click()
                    pagina.get_by_text("Dados extraídos e triagem — RF14 / RF15", exact=True).click()
                    literal = pagina.get_by_test_id("stJson").first
                    expect(literal).not_to_contain_text("2026-000142")
                    expect(literal).to_contain_text(re.compile(r'protocolo["\s:]*NULL', re.I))
                    expect(literal).to_contain_text(re.compile(r'data["\s:]*NULL', re.I))
                    expect(protocolo).to_have_value("")

                    menu.get_by_text(rag, exact=True).click()
                    pagina.get_by_role("tab", name="Atendimento integrado (RF20)", exact=True).click()
                    pagina.get_by_role("button", name="Executar Atendimento Integrado com RAG (RF20)").click()
                    assert not erros, erros
                    seletor = pagina.get_by_test_id("stSelectbox").filter(
                        has=pagina.get_by_text("Estado da Revisão:", exact=True))
                    expect(pagina.get_by_test_id("stStatusWidget")).not_to_be_visible(timeout=30000)
                    seletor.get_by_role("combobox").focus()
                    seletor.get_by_role("combobox").press("ArrowDown")
                    for opcao in ("Pendente", "Aprovar", "Rejeitar", "Revisar"):
                        expect(pagina.get_by_role("option", name=opcao, exact=True)).to_be_visible()
                    pagina.get_by_role("option", name="Revisar", exact=True).click()
                    botao = pagina.get_by_role("button", name="Registrar decisão humana", exact=True)
                    botao.click()
                    expect(pagina.get_by_text("Decisão persistida: REVISAR", exact=False)).to_be_visible()
                    expect(botao).to_be_disabled()
                    assert pagina.locator("html").get_attribute("lang") == "pt-BR"
                    assert pagina.locator("html").get_attribute("translate") == "no"
                    assert not erros, erros
                    menu.get_by_text(matriz, exact=True).click()
                    # Executa as mesmas asserções contratuais, sem mudar sua lógica.
                    pagina.get_by_role("button", name="Executar Todos os Testes (T01 a T15) ao Vivo").click()
                    expect(pagina.get_by_text("Executado ao Vivo nesta Sessão", exact=True)).to_be_visible(timeout=120000)
                    expect(pagina.get_by_test_id("stMetricValue").filter(has_text="15 / 15")).to_be_visible()
                    assert not erros, erros
                finally:
                    navegador.close()
        finally:
            servidor.terminate()
            servidor.wait(timeout=15)
