"""Reconhecimento dos rótulos que abrem cada dispositivo.

Uma linha do texto normativo começa, quase sempre, pelo rótulo do dispositivo
que ela inaugura — "Art. 5º", "§ 2º", "III -", "b)". Este módulo identifica esse
rótulo, devolve o tipo e a numeração, e separa o texto que vem depois dele.

As expressões são deliberadamente exigentes. O inciso, por exemplo, só é
reconhecido quando o algarismo romano vem seguido de travessão: sem isso,
qualquer linha iniciada por "I" ou "V" seria confundida com um. O mesmo vale
para o item, que exige contexto de alínea aberta — ver fragmentador.
"""
from __future__ import annotations

import re
import unicodedata

from .modelos import Tipo

# Ordinais e variantes de grafia: "1º", "1o", "1°", e ainda "5º-A" das inclusões
# posteriores. O ponto final é opcional porque a partir do décimo a lei passa a
# usar cardinal ("Art. 10.").
_NUM_ARTIGO = r"\d+\s*(?:[ºo°]|[.º])?(?:\s*-\s*[A-Z])?"
_NUM_PARAGRAFO = r"\d+\s*(?:[ºo°])?(?:\s*-\s*[A-Z])?"
_ROMANO = r"[IVXLCDM]+(?:\s*-\s*[A-Z])?"

PADROES: list[tuple[Tipo, re.Pattern]] = [
    (Tipo.ARTIGO, re.compile(
        rf"^Art(?:igo)?\s*\.?\s*(?P<num>{_NUM_ARTIGO})\s*[-–—.]?\s*(?P<resto>.*)$", re.I)),
    (Tipo.PARAGRAFO, re.compile(
        r"^(?P<num>Par[áa]grafo\s+[úu]nico)\s*[-–—.:]?\s*(?P<resto>.*)$", re.I)),
    (Tipo.PARAGRAFO, re.compile(
        rf"^§\s*(?P<num>{_NUM_PARAGRAFO})\s*[-–—.]?\s*(?P<resto>.*)$")),
    (Tipo.INCISO, re.compile(
        rf"^(?P<num>{_ROMANO})\s*[-–—]\s*(?P<resto>.*)$")),
    (Tipo.ALINEA, re.compile(
        r"^(?P<num>[a-z])\s*\)\s*(?P<resto>.*)$")),
    (Tipo.ITEM, re.compile(
        r"^(?P<num>\d+)\s*[.)]\s+(?P<resto>.*)$")),
]

AGRUPADORES: list[tuple[Tipo, re.Pattern]] = [
    (Tipo.PARTE, re.compile(r"^PARTE\s+(?P<num>[^\s].*)$", re.I)),
    (Tipo.LIVRO, re.compile(r"^LIVRO\s+(?P<num>[^\s].*)$", re.I)),
    (Tipo.TITULO, re.compile(r"^T[ÍI]TULO\s+(?P<num>[^\s].*)$", re.I)),
    (Tipo.CAPITULO, re.compile(r"^CAP[ÍI]TULO\s+(?P<num>[^\s].*)$", re.I)),
    (Tipo.SUBSECAO, re.compile(r"^SUBSE[ÇC][ÃA]O\s+(?P<num>[^\s].*)$", re.I)),
    (Tipo.SECAO, re.compile(r"^SE[ÇC][ÃA]O\s+(?P<num>[^\s].*)$", re.I)),
]

#: Fecho de promulgação: a partir dele o que vem é assinatura, não dispositivo.
#:
#: Exige cidade seguida de data por extenso ("Brasília, 30 de agosto de 1970"),
#: e não apenas o nome da cidade: topônimos aparecem com frequência no corpo da
#: lei, e um casamento frouxo encerraria o texto no meio.
#:
#: O prefixo é um trecho curto sem vírgula, e não uma repetição de palavras: um
#: grupo repetido com espaço opcional dentro provoca retrocesso catastrófico nas
#: linhas longas que nunca chegam à vírgula — e as linhas da lei são longas.
_FECHO = re.compile(
    r"^(?:[^,\n]{2,60},\s*\d{1,2}[ºo°]?\s+de\s+[^\s,]{3,20}\s+de\s+\d{4}"
    r"|Sala das Sess[õo]es)",
    re.I,
)


def _limpar_numero(num: str) -> str:
    """Normaliza a numeração mantendo a forma como a lei a escreve."""
    num = re.sub(r"\s+", "", num.strip())
    num = num.rstrip(".")
    # 'o' e '°' viram 'º': a mesma numeração aparece das três formas no acervo.
    num = num.replace("°", "º")
    num = re.sub(r"(?<=\d)o\b", "º", num)
    return num


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)
    )


def eh_fecho(linha: str) -> bool:
    """Indica o início do fecho (local, data e assinaturas)."""
    return bool(_FECHO.match(linha.strip()))


def eh_rubrica(linha: str) -> bool:
    """Rubrica de agrupador: linha curta em caixa alta, sem rótulo próprio.

    No acervo da Câmara a rubrica vem na linha seguinte ao agrupador
    ("CAPÍTULO I" / "DAS DISPOSIÇÕES GERAIS"), e é sempre em caixa alta.
    """
    bruta = linha.strip()
    if not bruta or len(bruta) > 120:
        return False
    letras = [c for c in _sem_acento(bruta) if c.isalpha()]
    if not letras:
        return False
    return all(c.isupper() for c in letras)


def reconhecer(linha: str) -> tuple[Tipo, str | None, str] | None:
    """Devolve (tipo, numero, resto) do rótulo que abre a linha, ou None.

    `resto` é o texto do dispositivo já sem o rótulo — pode vir vazio quando a
    lei quebra a linha logo após ele, caso frequente nas alíneas.
    """
    bruta = linha.strip()
    if not bruta:
        return None

    for tipo, padrao in AGRUPADORES:
        m = padrao.match(bruta)
        if m:
            return tipo, _limpar_numero(m.group("num")), ""

    for tipo, padrao in PADROES:
        m = padrao.match(bruta)
        if not m:
            continue
        num = m.group("num")
        if tipo is Tipo.PARAGRAFO and num.lower().startswith("par"):
            num = "único"
        else:
            num = _limpar_numero(num)
        return tipo, num, m.group("resto").strip()

    return None
