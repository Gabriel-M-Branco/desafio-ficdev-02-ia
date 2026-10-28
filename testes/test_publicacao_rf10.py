"""Endpoints ASGI locais: nenhum socket, provedor ou status real alterado."""
import asyncio
import hashlib

import httpx
import pytest
pytest.importorskip('fastapi', reason='FastAPI não instalado; testes HTTP locais indisponíveis')
from PIL import Image

from src.audit import AuditLogger
from src.image_generation import ImageGenerator
from src.image_access import exigir_revisor_imagem


@pytest.fixture
def fluxo(tmp_path, monkeypatch):
    import src.main as main
    gerador = ImageGenerator()
    gerador.output_dir = tmp_path / 'resultados/imagens'
    gerador.output_dir.mkdir(parents=True)
    imagem = gerador.output_dir / 'institucional.png'
    Image.new('RGB', (20, 20), 'blue').save(imagem)
    meta = {'sucesso': True, 'ia_gerada': True, 'arquivo_imagem': str(imagem),
            'sha256_imagem': hashlib.sha256(imagem.read_bytes()).hexdigest(),
            'estado_imagem': 'pendente_revisao', 'status_revisao': 'pendente_revisao',
            'provedor_efetivo': 'cloudflare', 'modelo_ia_utilizado': 'modelo-teste'}
    logger = AuditLogger(str(tmp_path / 'logs'))
    identificador = logger.registrar_execucao(modalidade='imagem', arquivo_origem=str(imagem),
        provedor='cloudflare', modelo='modelo-teste', versao_prompt='teste',
        parametros={}, resultado=meta, duracao_segundos=0)
    monkeypatch.setattr(main, 'image_generator', gerador)
    monkeypatch.setattr(main, 'audit_logger', logger)
    monkeypatch.setattr(main, 'BASE_DIR', tmp_path)
    app = main.app
    monkeypatch.setattr(app, 'dependency_overrides', {})
    for rota in main.app.routes:
        if getattr(rota, 'path', '') == '/arquivos':
            monkeypatch.setattr(rota.app, 'directory', str(tmp_path))
            monkeypatch.setattr(rota.app, 'all_directories', [str(tmp_path)])
    def pedir(metodo, url, **kwargs):
        async def executar():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://teste') as cliente:
                return await cliente.request(metodo, url, **kwargs)
        return asyncio.run(executar())
    corpo = {'id_execucao': identificador, 'hash_imagem': meta['sha256_imagem'],
             'decisao': 'APROVADO', 'justificativa': 'Conferencia de teste', 'operador': 'identidade-forjada'}
    return app, pedir, corpo, imagem, gerador, logger


def autenticar(app, permissoes=None):
    app.dependency_overrides[exigir_revisor_imagem] = lambda: {
        'sub': 'revisor-autenticado', 'permissoes': ['rf10:revisar'] if permissoes is None else permissoes}


def test_sem_autenticacao_admin_desabilitado_e_publicacao_bloqueada(fluxo):
    _, pedir, corpo, _, _, _ = fluxo
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 503
    assert pedir('GET', f"/api/revisao/imagem/{corpo['id_execucao']}/arquivo").status_code == 503
    assert pedir('GET', f"/api/publicacao/imagem/{corpo['id_execucao']}").status_code == 403


def test_cabecalhos_forjados_nao_autenticam(fluxo):
    _, pedir, corpo, _, _, _ = fluxo
    headers = {'Authorization': 'Bearer token-inventado', 'X-User': 'administrador', 'X-Role': 'admin'}
    assert pedir('POST', '/api/revisao/imagem', json=corpo, headers=headers).status_code == 503
    assert pedir('GET', f"/api/revisao/imagem/{corpo['id_execucao']}/arquivo", headers=headers).status_code == 503


@pytest.mark.parametrize('url', [
    '/arquivos/resultados%2Fimagens%2Finstitucional.png',
    '/arquivos/resultados/imagens/../imagens/institucional.png',
    '/arquivos/resultados/imagens/institucional.png?aprovado=true',
    '/arquivos/resultados/imagens/institucional.png?download=1',
])
def test_url_alternativa_nao_contorna_publicacao(fluxo, url):
    _, pedir, _, _, _, _ = fluxo
    assert pedir('GET', url).status_code == 404


def test_sem_permissao_e_sem_identidade(fluxo):
    app, pedir, corpo, _, _, _ = fluxo
    autenticar(app, [])
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 403
    app.dependency_overrides[exigir_revisor_imagem] = lambda: None
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 401


def test_aprovacao_publicacao_e_adulteracao(fluxo):
    app, pedir, corpo, imagem, _, _ = fluxo
    autenticar(app)
    assert pedir('GET', f"/api/revisao/imagem/{corpo['id_execucao']}/arquivo").content == imagem.read_bytes()
    resposta = pedir('POST', '/api/revisao/imagem', json=corpo)
    assert resposta.status_code == 200
    assert resposta.json()['metadados']['revisao_humana']['operador'] == 'revisor-autenticado'
    app.dependency_overrides.clear()
    url = f"/api/publicacao/imagem/{corpo['id_execucao']}"
    resposta = pedir('GET', url)
    assert resposta.status_code == 200 and resposta.content == imagem.read_bytes()
    assert resposta.headers['cache-control'] == 'no-store'
    imagem.write_bytes(imagem.read_bytes() + b'adulteracao')
    assert pedir('GET', url).status_code == 403


def test_rejeicao_posterior_revoga_aprovacao(fluxo):
    app, pedir, corpo, _, _, _ = fluxo
    autenticar(app)
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 200
    corpo['decisao'] = 'REJEITADO'
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 200
    assert pedir('GET', f"/api/publicacao/imagem/{corpo['id_execucao']}").status_code == 403


def test_aprovacao_antiga_sem_autenticacao_nao_publica(fluxo):
    _, pedir, corpo, _, gerador, logger = fluxo
    assert gerador.revisar_imagem(corpo['id_execucao'], corpo['hash_imagem'], 'APROVADO',
                                 'Declaracao sem autenticacao', 'Revisor declarado', logger)['sucesso']
    assert pedir('GET', f"/api/publicacao/imagem/{corpo['id_execucao']}").status_code == 403


@pytest.mark.parametrize('arquivo', ['institucional.png', 'arte_ia.png', 'manifesto.json'])
def test_url_direta_bloqueada_mesmo_depois_de_aprovar(fluxo, arquivo):
    app, pedir, corpo, imagem, _, _ = fluxo
    (imagem.parent / arquivo).write_bytes(imagem.read_bytes())
    url = '/arquivos/resultados/imagens/' + arquivo
    assert pedir('GET', url).status_code == 404
    autenticar(app)
    assert pedir('POST', '/api/revisao/imagem', json=corpo).status_code == 200
    assert pedir('GET', url).status_code == 404
