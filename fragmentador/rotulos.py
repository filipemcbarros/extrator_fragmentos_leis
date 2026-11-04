"""Reconhecimento dos rótulos que abrem cada dispositivo.

Uma linha do texto normativo começa, quase sempre, pelo rótulo do dispositivo
que ela inaugura — "Art. 5º", "§ 2º", "III -", "b)". Este módulo identifica esse
rótulo, devolve o tipo e a numeração, e separa o texto que vem depois dele.

As expressões são deliberadamente exigentes. O inciso, por exemplo, só é
reconhecido quando o algarismo romano vem seguido de travessão: sem isso,
qualquer linha iniciada por "I" ou "V" seria confundida com um. O mesmo vale
para o item, que exige contexto de enumeração aberta — ver fragmentador.

Representação de cada tipo, conforme a LC 95/1998, art. 10:

- artigo: "Art." e numeração ordinal até o nono, cardinal a partir dele (I);
- parágrafo: "§" e a mesma numeração, ou "Parágrafo único" por extenso (III);
- inciso: algarismo romano; alínea: letra minúscula; item: algarismo arábico (IV);
- Capítulo, Título, Livro e Parte: caixa alta e algarismo romano; a Parte pode
  ser Geral, Especial ou ordinal por extenso (VI);
- Seção e Subseção: algarismo romano, em minúsculas com inicial maiúscula (VII);
- Disposições Preliminares, Gerais, Finais ou Transitórias (VIII).

O acervo traz também leis anteriores à LC 95, com grafias que ela não prevê
("CAPITULO PRIMEIRO", "Seção 1ª", "1º) o curso…", "DISPOSIÇÕES GERAES"). Elas
são aceitas quando não há ambiguidade, porque o tipo do dispositivo é o mesmo.
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
#: Situação normativa que dispensa o travessão do inciso: "IV (VETADO);".
_SITUACAO = r"\(?\s*(?:VETAD|Vetad|vetad|REVOGAD|Revogad|revogad)"
#: Intervalo ou lista de numerações num só rótulo: "5º a 7º", "1º, 2º e 5º",
#: "5º - 6º - 7º". Só aparece em veto ou revogação agrupados.
_LISTA_NUM = (rf"{_NUM_PARAGRAFO}\.?(?:\s*(?:,|\ba\b|\be\b|-)\s*{_NUM_PARAGRAFO}\.?)+")

PADROES: list[tuple[Tipo, re.Pattern]] = [
    # Sem re.I: o rótulo é "Art." ou "ART."; "art. 6º" em minúscula é remissão
    # dentro do texto — por exemplo, o conteúdo de uma alínea de revogação.
    (Tipo.ARTIGO, re.compile(
        rf"^(?:Art|ART)(?:igo|IGO)?\s*\.?\s*(?P<num>{_NUM_ARTIGO})\s*[-–—.]?\s*(?P<resto>.*)$")),
    # Lei de um só artigo: "Artigo unico." na grafia antiga, e também
    # "Art. único." e "Artigo único:". Sem isto a lei inteira ficaria no preâmbulo.
    (Tipo.ARTIGO, re.compile(
        r"^(?:Art|ART)(?:igo|IGO)?\s*\.?\s*(?P<num>[ÚUúu]nico|[ÚU]NICO)\s*[-–—.:]?\s*(?P<resto>.*)$")),
    # Veto ou revogação agrupados: "Arts. 5º a 7º (VETADOS).". Sem a marca de
    # situação, "Arts. 82 e 83" é remissão ou tabela, e fica como texto.
    (Tipo.ARTIGO, re.compile(
        rf"^(?:Arts|ARTS)\s*\.?\s*(?P<num>{_LISTA_NUM})\s*[-–—.]?\s*(?P<resto>{_SITUACAO}.*)$")),
    (Tipo.PARAGRAFO, re.compile(
        r"^(?P<num>Par[áa]grafo\s+[úu]nico)\s*[-–—.:]?\s*(?P<resto>.*)$", re.I)),
    (Tipo.PARAGRAFO, re.compile(
        rf"^§§\s*(?P<num>{_LISTA_NUM})\s*[-–—.]?\s*(?P<resto>{_SITUACAO}.*)$")),
    (Tipo.PARAGRAFO, re.compile(
        rf"^§\s*(?P<num>{_NUM_PARAGRAFO})\s*[-–—.]?\s*(?P<resto>.*)$")),
    (Tipo.INCISO, re.compile(
        rf"^(?P<num>{_ROMANO})\s*[-–—]\s*(?P<resto>.*)$")),
    (Tipo.INCISO, re.compile(
        rf"^(?P<num>{_ROMANO})\s+(?P<resto>{_SITUACAO}.*)$")),
    (Tipo.ALINEA, re.compile(
        r"^(?P<num>[a-z])\s*\)\s*(?P<resto>.*)$")),
    # Item: "1.", "1)", "1 -" e, nas leis antigas, "1º)". O contexto de
    # enumeração é exigido pelo fragmentador, não aqui.
    (Tipo.ITEM, re.compile(
        r"^(?P<num>\d+(?:\s*[ºo°](?=\s*\)))?)\s*(?:[.)]|\s[-–—]|[-–—](?=\s))\s+(?P<resto>.*)$")),
]

#: Numeração dos agrupadores: romano ("IV", "IV-A"), "ÚNICO", ordinal por
#: extenso ("PRIMEIRA", "DÉCIMA SEGUNDA") ou arábico ordinal das leis antigas
#: ("1ª"), sem zero à esquerda: "Capítulo 08 – Frutos" é linha de tabela.
#: O romano aceita minúsculas ("Título ii", erro frequente de digitação no
#: acervo) e o romano partido por espaço ("Capítulo I I"); o lookahead impede
#: que ele engula a palavra seguinte.
_ORDINAL = (r"(?:PRIMEIR|SEGUND|TERCEIR|QUART|QUINT|SEXT|S[ÉE]TIM|OITAV|NON|"
            r"D[ÉE]CIM|VIG[ÉE]SIM|TRIG[ÉE]SIM)[OA]")
_NUM_AGRUPADOR = (
    rf"(?:(?i:[IVXLCDM]+(?: [IVX]+)*)(?:\s*-\s*[A-Z])?(?![^\W\d_])"
    rf"|(?i:[ÚU]NIC[OA])(?![^\W\d_])"
    rf"|(?i:{_ORDINAL}(?:\s+{_ORDINAL})?)(?![^\W\d_])"
    rf"|[1-9]\d*\s*[ºª°o]?(?!\w))"
)


def _agrupador(palavra: str, numeracao: str = _NUM_AGRUPADOR) -> re.Pattern:
    """Rótulo de agrupador: a palavra, a numeração e, opcional, a rubrica.

    A palavra começa por maiúscula ("CAPÍTULO", "Capítulo"): em minúscula é
    texto corrido — "parte do valor", "título de eleitor". O restante da
    palavra aceita caixa mista ("CAPíTULO", "TíTULO"), como no acervo. Depois
    da numeração só pode vir nada, um separador seguido da rubrica, ou a
    rubrica; qualquer outra coisa ("Capítulo VI desta Lei") é remissão.
    """
    return re.compile(
        rf"^{palavra[0]}(?i:{palavra[1:]})\s+(?P<num>{numeracao})"
        rf"(?P<resto>\s*(?:[-–—.:]\s*.*)?|\s+.*)$")


AGRUPADORES: list[tuple[Tipo, re.Pattern]] = [
    # A Parte pode ser Geral ou Especial (art. 10, VI); nas leis antigas há
    # também Preliminar, Processual e Final.
    (Tipo.PARTE, _agrupador(
        "PARTE", rf"(?i:GERAL|ESPECIAL|PRELIMINAR|PROCESSUAL|FINAL)(?![^\W\d_])|{_NUM_AGRUPADOR}")),
    # "LIVRO COMPLEMENTAR": o livro final do Código Civil, fora da numeração.
    (Tipo.LIVRO, _agrupador("LIVRO", rf"(?i:COMPLEMENTAR)(?![^\W\d_])|{_NUM_AGRUPADOR}")),
    (Tipo.TITULO, _agrupador("T[ÍI]TULO")),
    (Tipo.CAPITULO, _agrupador("CAP[ÍI]TULO")),
    (Tipo.SUBSECAO, _agrupador("SUBSE[ÇC][ÃA]O")),
    (Tipo.SECAO, _agrupador("SE[ÇC][ÃA]O")),
]

#: Rubrica fora da caixa alta na mesma linha do rótulo: "Seção II Da Fixação da
#: Despesa". Começa por "Da", "Do", "Das", "Dos" ou "De" e palavra maiúscula.
_RUBRICA_MISTA = re.compile(r"^D[aoe]s?\s+[A-ZÀ-Ý]")

#: Agrupamento do art. 10, VIII, na linha inteira: "DISPOSIÇÕES FINAIS",
#: "Das Disposições Gerais e Transitórias", "DISPOSIÇÕES GERAES:".
_ADJ_DISPOSICOES = r"(?:PRELIMINAR(?:ES)?|GERA(?:IS|ES|L)|FINA(?:IS|ES|L)|TRANSIT[ÓO]RIAS?)"
DISPOSICOES = re.compile(
    rf"^(?i:(?:DAS?\s+)?DISPOSI[ÇC](?:[ÕO]ES|[ÃA]O)\s+{_ADJ_DISPOSICOES}"
    rf"(?:\s*(?:,|\bE\b)\s*{_ADJ_DISPOSICOES})*)\s*[.:]?$")

#: Fecho de promulgação: a partir dele o que vem é assinatura, não dispositivo.
#:
#: Exige cidade seguida de data por extenso ("Brasília, 30 de agosto de 1970",
#: ou "Brasília, em 3 de julho de 2026" nas leis promulgadas pelo Congresso),
#: e não apenas o nome da cidade: topônimos aparecem com frequência no corpo da
#: lei, e um casamento frouxo encerraria o texto no meio.
#:
#: O prefixo é um trecho curto sem vírgula, e não uma repetição de palavras: um
#: grupo repetido com espaço opcional dentro provoca retrocesso catastrófico nas
#: linhas longas que nunca chegam à vírgula — e as linhas da lei são longas.
_FECHO = re.compile(
    r"^(?:[^,\n]{2,60},\s*(?:em\s+)?\d{1,2}[ºo°]?\s+de\s+[^\s,]{3,20}\s+de\s+\d{4}"
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


def _limpar_agrupador(num: str) -> str:
    """Numeração de agrupador: espaços simples, sem os do sufixo ("IV-A")."""
    num = re.sub(r"\s+", " ", num.strip()).replace("°", "º")
    num = re.sub(r"\s*-\s*", "-", num)
    # Romano sempre em maiúsculas e sem espaço: "ii", "Iii" e "I I" são erros
    # de digitação da fonte.
    if re.fullmatch(r"(?i:[IVXLCDM]+(?: [IVX]+)*)(?:-[A-Z])?", num):
        num = num.upper().replace(" ", "")
    return num


def _limpar_lista(num: str) -> str:
    """Intervalo ou lista ("5º a 7º", "1º, 2º e 5º"): cada número limpo, separadores mantidos."""
    partes = re.split(r"(\s*(?:,|\ba\b|\be\b|\s-\s)\s*)", num.strip())
    return "".join(
        _limpar_numero(p) if i % 2 == 0 else (", " if p.strip() == "," else f" {p.strip()} ")
        for i, p in enumerate(partes))


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
    lei quebra a linha logo após ele, caso frequente nas alíneas. Nos
    agrupadores, `resto` é a rubrica que vem na mesma linha ("CAPÍTULO III –
    DAS PENALIDADES"); nas disposições, é a linha inteira.
    """
    bruta = linha.strip()
    if not bruta:
        return None

    for tipo, padrao in AGRUPADORES:
        m = padrao.match(bruta)
        if not m:
            continue
        resto = m.group("resto").strip()
        if resto[:1] in ("-", "–", "—", ".", ":"):
            resto = resto.lstrip("-–—.: ")
        elif resto and not (eh_rubrica(resto) or _RUBRICA_MISTA.match(resto)
                            or DISPOSICOES.match(resto)):
            # "Capítulo VI desta Lei": a palavra abre uma remissão, não um agrupador.
            return None
        # `resto` é a rubrica, quando vem na mesma linha do rótulo.
        return tipo, _limpar_agrupador(m.group("num")), resto

    if DISPOSICOES.match(bruta) and bruta[0].isupper():
        # O agrupamento não tem numeração: o nome dele é a própria rubrica.
        return Tipo.DISPOSICOES, None, bruta

    for tipo, padrao in PADROES:
        m = padrao.match(bruta)
        if not m:
            continue
        num = m.group("num")
        if _sem_acento(num).lower().endswith("unico"):
            # "Parágrafo único", "Artigo unico": uma só forma na saída.
            num = "único"
        elif re.search(r"\d\s*[ºo°]?\.?\s*(?:,|\ba\b|\be\b|-\s*\d)", num):
            num = _limpar_lista(num)
        else:
            num = _limpar_numero(num)
        return tipo, num, m.group("resto").strip()

    return None
