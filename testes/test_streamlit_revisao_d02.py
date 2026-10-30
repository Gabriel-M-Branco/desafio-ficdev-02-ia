"""T11 pela interface real: somente em cópia descartável do projeto."""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("FICDEV_TEST_COPY") != "1",
                                reason="Use testes/executar_isolado.py para preservar logs e dados reais.")


def widget(elementos, label):
    return next(e for e in elementos if e.label == label)


def preparar():
    from streamlit.testing.v1 import AppTest
    from src import BASE_DIR
    at = AppTest.from_file(str(BASE_DIR / "src" / "app.py"), default_timeout=30).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("6. Assistente de Documentos RAG (RF18-RF21)").run()
    assert not at.exception
    widget(at.button, "Executar Atendimento Integrado com RAG (RF20)").click().run()
    assert not at.exception
    return at, BASE_DIR


def test_aprovar_rejeitar_revisar_pela_interface():
    at, base = preparar()
    assert widget(at.selectbox, "Estado da Revisão:").options == ["Pendente", "Aprovar", "Rejeitar", "Revisar"]
    eid = at.session_state["rag_atendimento_resultado"]["id_execucao"]
    for estado, esperado in (("aprovada", "APROVADO"), ("rejeitada", "REJEITADO"), ("revisar", "CORRIGIDO")):
        widget(at.selectbox, "Estado da Revisão:").set_value(estado)
        widget(at.text_input, "Identificação do operador:").set_value("Operadora de teste T11").run()
        widget(at.button, "Registrar decisão humana").click().run()
        assert not at.exception
        dado = json.loads((base / "resultados" / "logs" / f"{eid}.json").read_text(encoding="utf-8"))
        assert dado["decisao_humana"]["status"] == esperado
        assert dado["decisao_humana"]["operador"] == "Operadora de teste T11"
        assert dado["decisao_humana"]["data_decisao"]
        assert at.session_state["rag_atendimento_resultado"]["status_operador"] == estado
        assert any(f"Decisão persistida: {estado.upper()}" in e.value for e in at.success)
        assert widget(at.button, "Registrar decisão humana").disabled
        trilha = base / "resultados/logs/audit_trail.jsonl"
        antes = trilha.read_bytes()
        # Rerenderizar o comprovante não deve repetir a gravação.
        at.run()
        assert trilha.read_bytes() == antes
        # Uma submissão já enfileirada também deve ser idempotente na sessão.
        at.session_state["registrando_decisao"] = True
        at.run()
        assert trilha.read_bytes() == antes

    at.sidebar.radio[0].set_value("5. Auditoria e LGPD (RF11/RF12/RF13)").run()
    assert not at.exception
    widget(at.selectbox, "Filtrar por Status de Decisão:").set_value("Revisar").run()
    assert any("REVISÃO SOLICITADA" in e.value for e in at.markdown)


def test_falha_de_persistencia_nao_mostra_sucesso():
    at, base = preparar()
    eid = at.session_state["rag_atendimento_resultado"]["id_execucao"]
    # Remove apenas um registro recém-criado dentro da cópia temporária.
    arquivo = base / "resultados" / "logs" / f"{eid}.json"
    assert base.is_relative_to(Path(os.environ.get("TEMP", "/tmp")))
    arquivo.unlink()
    widget(at.selectbox, "Estado da Revisão:").set_value("aprovada")
    widget(at.button, "Registrar decisão humana").click().run()
    assert any("não foi salva" in e.value for e in at.error)
    assert at.session_state["rag_atendimento_resultado"]["status_operador"] == "pendente"


def test_editar_texto_descarta_envelope_do_exemplo():
    from streamlit.testing.v1 import AppTest
    from src import BASE_DIR
    at = AppTest.from_file(str(BASE_DIR / "src/app.py"), default_timeout=30).run()
    at.sidebar.radio[0].set_value("7. Triagem e Ficha da Solicitacao (RF14/RF15)").run()
    assert not at.exception
    assert at.session_state["ficha_protocolo"]
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert json.loads(at.json[0].value)["protocolo"] == "2026-000142"
    # Sequência exata do teste manual: apagar texto, apagar campo, digitar.
    widget(at.text_area, "Texto da Manifestação:").set_value("").run()
    widget(at.text_input, "Protocolo Externo (opcional):").set_value("").run()
    for texto in ("Solicito apenas Auxílio Transporte.", "Gostaria de cancelar minha matrícula."):
        widget(at.text_area, "Texto da Manifestação:").set_value(texto).run()
        assert not at.exception
        assert at.session_state["ficha_protocolo"] == ""
        assert at.session_state["ficha_data_externa"] is None
        widget(at.button, "Processar Ficha Pydantic").click().run()
        assert not at.exception
        literal = json.loads(at.json[0].value)
        assert literal["protocolo"] is None
        assert literal["data"] is None
    # Um protocolo novo só pode vir do texto ou de preenchimento explícito.
    widget(at.text_input, "Protocolo Externo (opcional):").set_value("2026-123456").run()
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert json.loads(at.json[0].value)["protocolo"] == "2026-123456"
    widget(at.text_input, "Protocolo Externo (opcional):").set_value("").run()
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert json.loads(at.json[0].value)["protocolo"] is None
    at.sidebar.radio[0].set_value("8. Painel de Sentimentos (RF22)").run()
    at.sidebar.radio[0].set_value("7. Triagem e Ficha da Solicitacao (RF14/RF15)").run()
    assert not at.exception
    assert at.session_state["ficha_protocolo"]
    assert at.session_state["ficha_data_externa"]


def test_exemplos_preservam_envelope_e_campo_apagado_nao_retorna():
    from streamlit.testing.v1 import AppTest
    from src import BASE_DIR
    casos = json.loads((BASE_DIR / "dados/solicitacoes/solicitacoes.json").read_text(encoding="utf-8"))
    at = AppTest.from_file(str(BASE_DIR / "src/app.py"), default_timeout=30).run()
    at.sidebar.radio[0].set_value("7. Triagem e Ficha da Solicitacao (RF14/RF15)").run()
    for caso in casos:
        widget(at.selectbox, "Carregar Solicitação de Teste:").set_value(f"{caso['id']} ({caso['subtipo']})").run()
        widget(at.button, "Processar Ficha Pydantic").click().run()
        assert not at.exception
        literal = json.loads(at.json[0].value)
        # O acervo de exemplos usa sentinelas; o contrato D02 usa None.
        def esperado(campo):
            valor = caso.get(campo)
            return None if valor in (None, "", "não localizado", "null", "None") else valor
        assert literal["protocolo"] == esperado("protocolo")
        assert literal["data"] == esperado("data")
    primeiro = casos[0]
    widget(at.selectbox, "Carregar Solicitação de Teste:").set_value(f"{primeiro['id']} ({primeiro['subtipo']})").run()
    widget(at.text_input, "Protocolo Externo (opcional):").set_value("").run()
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert json.loads(at.json[0].value)["protocolo"] is None


def test_processamento_descarta_protocolo_residual_do_exemplo():
    from streamlit.testing.v1 import AppTest
    from src import BASE_DIR
    at = AppTest.from_file(str(BASE_DIR / "src/app.py"), default_timeout=30).run()
    at.sidebar.radio[0].set_value("7. Triagem e Ficha da Solicitacao (RF14/RF15)").run()
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert json.loads(at.json[0].value)["protocolo"] == "2026-000142"
    widget(at.text_area, "Texto da Manifestação:").set_value("Solicito apenas Auxílio Transporte.").run()
    # Simula a reconciliação tardia do widget com o envelope anterior.
    at.session_state["ficha_protocolo"] = "2026-000142"
    at.session_state["ficha_protocolo_confirmado"] = "2026-000142"
    at.run()
    widget(at.button, "Processar Ficha Pydantic").click().run()
    assert not at.exception
    literal = json.loads(at.json[0].value)
    assert literal["protocolo"] is None
    assert literal["data"] is None
