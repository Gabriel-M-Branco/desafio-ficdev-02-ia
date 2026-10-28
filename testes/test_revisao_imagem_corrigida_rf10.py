"""Revisão da última composição em cópia temporária, sem inferência."""
import hashlib
import json
from pathlib import Path

import pytest

from src import BASE_DIR
from src.audit import AuditLogger
from src.image_generation import ImageGenerator
from src.web_files import arquivo_publico


@pytest.fixture
def copia(tmp_path, monkeypatch):
    origem = BASE_DIR / 'resultados/imagens/validacao_cloudflare_rf10_educacional_d08ea1c2bd2c444f9f8bd0d048f9d775_placa_corrigida_1dc83800.json'
    if origem.is_file():
        meta = json.loads(origem.read_text(encoding='utf-8'))
        imagem = BASE_DIR / meta['arquivo_imagem']
        img_bytes = imagem.read_bytes()
    else:
        # Fixture sintética auto-contida para permitir execução mesmo após limpeza de resultados
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), "#004A8F").save(buf, format="PNG")
        img_bytes = buf.getvalue()
        sha256_img = hashlib.sha256(img_bytes).hexdigest()
        meta = {
            "sucesso": True,
            "ia_gerada": True,
            "estado_imagem": "pendente_revisao",
            "status_revisao": "pendente_revisao",
            "sha256_imagem": sha256_img,
            "provedor_efetivo": "cloudflare",
            "modelo_ia_utilizado": "@cf/black-forest-labs/flux-1-schnell",
            "arquivo_imagem": "corrigida.png"
        }
    destino = tmp_path / 'corrigida.png'
    destino.write_bytes(img_bytes)
    meta['arquivo_imagem'] = str(destino)
    meta['sha256_imagem'] = hashlib.sha256(img_bytes).hexdigest()
    gerador = ImageGenerator()
    gerador.output_dir = tmp_path
    monkeypatch.setattr(gerador, '_gerar_ilustracao_ia', lambda *a: pytest.fail('Inferência proibida'))
    logger = AuditLogger(str(tmp_path / 'logs'))
    identificador = logger.registrar_execucao(
        modalidade='imagem', arquivo_origem=str(destino), provedor=meta['provedor_efetivo'],
        modelo=meta['modelo_ia_utilizado'], versao_prompt='Copia temporaria de teste',
        parametros={}, resultado=meta, duracao_segundos=0)
    return gerador, logger, identificador, meta, destino


@pytest.mark.parametrize('decisao,estado', [('APROVADO', 'aprovada'), ('REJEITADO', 'rejeitada')])
def test_decisao_da_imagem_corrigida(copia, decisao, estado):
    gerador, logger, identificador, meta, imagem = copia
    resultado = gerador.revisar_imagem(identificador, meta['sha256_imagem'], decisao,
                                      'Conferencia visual de teste', 'Revisor ficticio', logger)
    assert resultado['sucesso']
    assert resultado['metadados']['estado_imagem'] == estado
    revisao = resultado['metadados']['revisao_humana']
    assert revisao['operador'] and revisao['justificativa'] and revisao['data_decisao']
    assert revisao['hash_imagem'] == hashlib.sha256(imagem.read_bytes()).hexdigest()
    log = json.loads((logger.log_dir / (resultado['id_execucao']+'.json')).read_text(encoding='utf-8'))
    assert log['decisao_humana'] == revisao


def test_alteracao_posterior_diverge_da_aprovacao_historica(copia):
    gerador, logger, identificador, meta, imagem = copia
    aprovado = gerador.revisar_imagem(identificador, meta['sha256_imagem'], 'APROVADO',
                                     'Conferido em teste', 'Revisor ficticio', logger)
    assert aprovado['sucesso']
    imagem.write_bytes(imagem.read_bytes() + b'alteracao')
    assert hashlib.sha256(imagem.read_bytes()).hexdigest() != aprovado['metadados']['revisao_humana']['hash_imagem']
    assert not gerador.revisar_imagem(identificador, meta['sha256_imagem'], 'APROVADO',
                                     'Nova tentativa', 'Revisor ficticio', logger)['sucesso']
    # Limitação atual: o manifesto histórico continua aprovado; não é estado dinâmico.
    assert aprovado['metadados']['estado_imagem'] == 'aprovada'


@pytest.mark.parametrize('estado', ['pendente_revisao', 'rejeitada'])
def test_download_direto_bloqueado_para_imagem_sem_aprovacao(tmp_path, estado):
    pasta = tmp_path / 'resultados/imagens'
    pasta.mkdir(parents=True)
    (pasta / 'imagem.png').write_bytes(b'cenario de teste')
    (pasta / 'imagem.json').write_text(json.dumps({'estado_imagem': estado}))
    assert not arquivo_publico(tmp_path, 'resultados/imagens/imagem.png')
