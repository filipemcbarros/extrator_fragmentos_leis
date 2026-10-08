"""Obtenção do HTML, por URL ou arquivo local."""
from __future__ import annotations

import pathlib

import requests

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def baixar(url: str, tempo_limite: int = 60) -> str:
    """Baixa a página e devolve o HTML como texto."""
    resposta = requests.get(url, headers=CABECALHOS, timeout=tempo_limite)
    resposta.raise_for_status()
    return decodificar(resposta.content)


def decodificar(conteudo: bytes) -> str:
    """Decodifica o HTML sem confiar no charset declarado.

    O acervo mistura páginas recentes em UTF-8 com antigas em Latin-1, e nem
    sempre o cabeçalho HTTP diz a verdade. Bytes Latin-1 com acento quase nunca
    formam UTF-8 válido, então a tentativa estrita em UTF-8 é um teste confiável;
    se falha, o texto é Windows-1252, superconjunto do Latin-1 que ainda cobre as
    aspas curvas e o travessão.
    """
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")


def ler(caminho: str | pathlib.Path) -> str:
    """Lê o HTML de um arquivo local."""
    return decodificar(pathlib.Path(caminho).read_bytes())


def obter(referencia: str) -> str:
    """Aceita URL ou caminho de arquivo e devolve o HTML."""
    if referencia.startswith(("http://", "https://")):
        return baixar(referencia)
    return ler(referencia)
