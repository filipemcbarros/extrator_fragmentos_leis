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
    # Páginas antigas do acervo declaram o charset só no meta; sem isto, acentos
    # chegam trocados quando o cabeçalho HTTP omite a codificação.
    if not resposta.encoding or resposta.encoding.lower() == "iso-8859-1":
        resposta.encoding = resposta.apparent_encoding or "utf-8"
    return resposta.text


def ler(caminho: str | pathlib.Path) -> str:
    """Lê o HTML de um arquivo local."""
    return pathlib.Path(caminho).read_text(encoding="utf-8", errors="replace")


def obter(referencia: str) -> str:
    """Aceita URL ou caminho de arquivo e devolve o HTML."""
    if referencia.startswith(("http://", "https://")):
        return baixar(referencia)
    return ler(referencia)
