"""Ausência na referência não é dado incorreto nem acerto artificial."""
import pytest
from src.audit import QualityEvaluator


@pytest.mark.parametrize("valor", ["não localizado", " NAO LOCALIZADO ", "na\u0303o\tlocalizado",
    "não\u00a0 localizado", "não_localizado", "não-localizado", "não\u2011localizado",
    "não localizado.", "NÃO LOCALIZADA", "não\u200b localizado", "", None])
def test_ausencias_equivalentes_sao_pendencias_sem_divergencia(valor):
    r = QualityEvaluator.avaliar_extracao({"telefone": valor}, {"campos_esperados": {"telefone": "não localizado"}})
    assert r["comparativo_campos"][0]["status"] == "PENDENCIA"
    assert r["erros_encontrados"] == []
    assert r["total_acertos"] == 0
    assert r["total_campos_avaliaveis"] == 0
    assert r["taxa_fidelidade_percentual"] is None


def test_quatro_campos_ausentes_nao_penalizam_dados_disponiveis():
    esperados = {"solicitante": "João Fictício", **dict.fromkeys(["nome_pai", "telefone", "orgao_expedidor", "uf"], "não localizado")}
    obtidos = {**esperados, "solicitante": "  JOA\u0303O\u00a0 FICTÍCIO "}
    r = QualityEvaluator.avaliar_extracao(obtidos, {"campos_esperados": esperados})
    assert r["total_campos_analisados"] == 5
    assert r["total_acertos"] == r["total_campos_avaliaveis"] == 1
    assert r["total_pendencias"] == r["total_ausentes_na_fonte"] == 4
    assert r["taxa_fidelidade_percentual"] == r["taxa_completude_percentual"] == 100
    assert not r["erros_encontrados"]


def test_omissao_de_dado_presente_continua_penalizando_extracao():
    r = QualityEvaluator.avaliar_extracao({}, {"campos_esperados": {"protocolo": "2099-123456"}})
    assert r["comparativo_campos"][0]["status"] == "PENDENCIA"
    assert r["total_omissoes_extracao"] == 1
    assert r["taxa_fidelidade_percentual"] == r["taxa_completude_percentual"] == 0
    assert not r["erros_encontrados"]


@pytest.mark.parametrize("esperado,obtido", [("não localizado", "valor inventado"), ("2099-123456", "2099-999999")])
def test_dado_inventado_ou_incorreto_continua_divergente(esperado, obtido):
    r = QualityEvaluator.avaliar_extracao({"protocolo": obtido}, {"campos_esperados": {"protocolo": esperado}})
    assert len(r["erros_encontrados"]) == 1
    assert r["comparativo_campos"][0]["status"] == "DIVERGENTE"
    assert r["total_acertos"] == 0
    assert r["taxa_fidelidade_percentual"] == 0
