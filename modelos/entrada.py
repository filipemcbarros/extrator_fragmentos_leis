"""Do HTML guardado na coleta para o trecho que vai no prompt.

A página inteira tem em média 48 KB, quase tudo menu, cabeçalho e rodapé do
sítio; o texto da lei fica em `div.textoNorma` e tem mediana de 1,7 KB. É esse
bloco que o modelo recebe — o mesmo de onde o regex parte.
"""
from __future__ import annotations

import re

from lxml import etree, html as lhtml

from fragmentador.extracao import extrair


def preparar(html_bruto: str, formato: str = "html") -> str:
    """Devolve a lei no formato pedido: "html" ou "texto"."""
    extraido = extrair(html_bruto)
    if formato == "html":
        norma = lhtml.fromstring(html_bruto).xpath('//div[contains(@class,"textoNorma")]')
        if norma:
            return f"<h1>{extraido.titulo}</h1>\n{_enxugar(norma[0])}"
    # Página fora do padrão Legin, ou formato "texto": as linhas extraídas. Elas
    # já passaram pelos reparos do regex (rótulo partido, rótulo colado).
    partes = [extraido.titulo, extraido.ementa, *extraido.linhas]
    return "\n".join(p for p in partes if p)


#: Onde a lei pode ser cortada: depois de uma quebra de linha ou do fim de um
#: bloco. São marcas da diagramação, e não dos rótulos — dividir pelos artigos
#: seria entregar ao modelo parte do trabalho que se quer medir.
_QUEBRA = re.compile(r"(?<=<br>)|(?<=</p>)|(?<=</table>)|(?<=\n)")


def dividir(entrada: str, contar, limite: int) -> list[str]:
    """Divide a lei em trechos de até `limite` tokens. A lei curta sai inteira.

    `contar` devolve o número de tokens de um texto no tokenizador do modelo.
    """
    if contar(entrada) <= limite:
        return [entrada]

    trechos: list[str] = []
    atual: list[str] = []
    tokens = 0
    for segmento in _QUEBRA.split(entrada):
        for pedaco in _caber(segmento, contar, limite):
            n = contar(pedaco)
            if atual and tokens + n > limite:
                trechos.append("".join(atual))
                atual, tokens = [], 0
            atual.append(pedaco)
            tokens += n
    if atual:
        trechos.append("".join(atual))
    return trechos


def _caber(segmento: str, contar, limite: int) -> list[str]:
    """Parte por palavras o segmento que sozinho excede o limite (linha sem quebra)."""
    n = contar(segmento)
    if n <= limite:
        return [segmento] if segmento else []
    palavras = segmento.split(" ")
    passo = max(1, len(palavras) * limite // (n + limite))
    return [" ".join(palavras[i:i + passo]) + " " for i in range(0, len(palavras), passo)]


def _enxugar(elemento) -> str:
    """Serializa o bloco sem o que só gasta tokens: scripts, comentários, atributos."""
    etree.strip_elements(elemento, etree.Comment, "script", "style", with_tail=False)
    for e in elemento.iter():
        # `class` fica: é ela que distingue a ementa do corpo.
        classe = e.get("class")
        e.attrib.clear()
        if classe:
            e.set("class", classe)
    bruto = lhtml.tostring(elemento, encoding="unicode")
    bruto = bruto.replace("\xa0", " ").replace("&nbsp;", " ").replace("&#160;", " ")
    bruto = re.sub(r"[ \t\r]+", " ", bruto)
    return re.sub(r"\s*\n\s*", "\n", bruto).strip()
