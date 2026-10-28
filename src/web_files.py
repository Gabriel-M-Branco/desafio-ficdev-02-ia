"""Restringe downloads públicos aos artefatos, sem expor código ou credenciais."""
from pathlib import Path


def arquivo_publico(base, caminho):
    base = Path(base).resolve()
    if Path(caminho).is_absolute():
        return False
    arquivo = (base / caminho).resolve()
    try:
        partes = arquivo.relative_to(base).parts
    except ValueError:
        return False
    if any(parte.startswith(".") for parte in partes):
        return False
    # RF10: arte bruta, composição e manifestos somente pelo fluxo administrativo.
    # Publicação tem rota própria, com revisão vigente e conferência dos bytes.
    if partes[:2] == ("resultados", "imagens"):
        return False
    if arquivo.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf", ".mp3", ".wav", ".json", ".jsonl", ".txt"}:
        return False
    return (partes[:1] == ("resultados",) or
            partes[:2] in {("dados", "originais"), ("dados", "processados")})
