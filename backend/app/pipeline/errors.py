class PipelineError(Exception):
    """Erro esperado do pipeline, com mensagem amigável para o usuário."""

    retryable = True


class FatalPipelineError(PipelineError):
    """Erro que não adianta tentar de novo (arquivo inválido, vídeo indisponível...)."""

    retryable = False


class Cancelled(Exception):
    """A tarefa foi cancelada pelo usuário."""
