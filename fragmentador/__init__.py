"""Fragmentador de leis: lê a página de uma lei e devolve os seus dispositivos.

Uso típico:

    from fragmentador import fragmentar_referencia

    lei = fragmentar_referencia(
        "https://www2.camara.leg.br/legin/fed/lei/1970-1979/"
        "lei-5603-30-agosto-1970-375011-publicacaooriginal-1-pl.html"
    )
    for artigo in lei.por_tipo(Tipo.ARTIGO):
        print(artigo.rotulo, artigo.texto[:80])
"""
from .extracao import TextoExtraido, extrair
from .fonte import baixar, ler, obter
from .fragmentador import fragmentar, fragmentar_html
from .modelos import AVULSOS, NIVEL, Fragmento, Lei, Tipo

__all__ = [
    "AVULSOS",
    "Fragmento",
    "Lei",
    "NIVEL",
    "TextoExtraido",
    "Tipo",
    "baixar",
    "extrair",
    "fragmentar",
    "fragmentar_html",
    "fragmentar_referencia",
    "ler",
    "obter",
]


def fragmentar_referencia(referencia: str) -> Lei:
    """Lê a referência (URL ou arquivo) e devolve a lei fragmentada."""
    return fragmentar_html(obter(referencia), origem=referencia)
