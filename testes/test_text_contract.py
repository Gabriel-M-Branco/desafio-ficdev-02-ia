"""Contrato JSON puro: não executa provedores nem corrige dados por adivinhação."""
import json
import pytest
from src.text_contract import ContratoTextoInvalido, interpretar_minuta


@pytest.mark.parametrize("cerca", [None, "json", "JSON", ""])
def test_json_ou_cerca_completa_preserva_conteudo(cerca):
    dado = {"extracao": {"protocolo": "não localizado"}, "minuta_institucional": "Minuta com acentuação e `símbolo`."}
    texto = json.dumps(dado, ensure_ascii=False)
    if cerca is not None:
        texto = f"```{cerca}\n{texto}\n```"
    assert interpretar_minuta(texto) == dado


@pytest.mark.parametrize("texto", [
    'Texto antes: {"extracao":{},"minuta_institucional":"Minuta"}',
    '{"extracao":{},"minuta_institucional":"Minuta"} Texto depois',
    '{"extracao":{},"minuta_institucional":"Minuta",}',
    '[]', '{}', '{"extracao":{}}', '{"minuta_institucional":"Minuta"}',
    '{"extracao":null,"minuta_institucional":"Minuta"}',
    '{"extracao":{},"minuta_institucional":" "}',
    '{"extracao":{},"minuta_institucional":12}',
    '{"extracao":{"protocolo":null},"minuta_institucional":"Minuta"}',
    '{"extracao":{},"extracao":{},"minuta_institucional":"Minuta"}',
    '{"extracao":{"protocolo":NaN},"minuta_institucional":"Minuta"}',
])
def test_invalido_nunca_vira_documento_ficticio(texto):
    with pytest.raises(ContratoTextoInvalido):
        interpretar_minuta(texto)


def test_truncamento_mesmo_com_objeto_parseavel_e_recusado():
    with pytest.raises(ContratoTextoInvalido) as erro:
        interpretar_minuta('{"extracao":{},"minuta_institucional":"Texto"}', "length")
    assert erro.value.codigo == "saida_truncada"
