"""Validação manual RF07: exige decisão humana explícita antes da síntese real."""
import json
from src.audio import AudioProcessor
from src.audit import AuditLogger


def main():
    texto = input("Texto exato da minuta fictícia a revisar: ")
    if not texto.strip():
        raise SystemExit("Texto vazio; nenhuma síntese executada.")
    print("\nRevise o texto acima. O áudio avisará sobre qualquer 'não localizado'.")
    if input("Digite APROVAR para autorizar este texto exato: ") != "APROVAR":
        raise SystemExit("Não aprovado; nenhuma síntese executada.")
    justificativa = input("Justificativa da aprovação: ").strip()
    operador = input("Identificação do responsável: ").strip()
    if not justificativa or not operador:
        raise SystemExit("Justificativa e responsável obrigatórios.")
    logger = AuditLogger()
    identificador = logger.registrar_execucao("texto", "", "revisao_manual", "N/A", "N/A", {}, {}, 0)
    if not logger.atualizar_decisao_humana(identificador, "APROVADO", justificativa, operador, texto):
        raise SystemExit("Falha ao persistir aprovação; síntese bloqueada.")
    resultado = AudioProcessor().sintetizar_minuta_audio(texto, "validacao_rf07.wav", identificador, logger)
    print(json.dumps({k: v for k, v in resultado.items() if k != "texto_sintetizado"}, ensure_ascii=False, indent=2))
    if not resultado["sucesso"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
