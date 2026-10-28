"""Central Inteligente de Atendimento e Comunicação Institucional - GOV.MT"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def resolver_caminho(caminho: str | Path | None) -> Path:
    """Resolve caminhos relativos de forma agnóstica a partir da raiz do projeto."""
    if caminho is None:
        return BASE_DIR
    p = Path(caminho)
    return p if p.is_absolute() else (BASE_DIR / p)


def caminho_relativo(caminho: str | Path | None) -> str:
    """Converte um caminho para formato relativo à raiz do projeto em padrão POSIX."""
    if caminho is None:
        return ""
    p = Path(caminho).resolve()
    try:
        return p.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return Path(caminho).as_posix()


__version__ = "1.0.0"

