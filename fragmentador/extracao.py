"""Do HTML da página para as linhas de texto da lei.

A fonte de referência é o acervo Legin da Câmara dos Deputados, cujas páginas
trazem o texto em `div.textoNorma`, com a ementa em `p.ementa` e o corpo em
`div.texto`, articulado por `<br>`. Há também um extrator genérico, para páginas
de outra origem: ele descarta cabeçalho, rodapé, menus e scripts e aproveita o
maior bloco de texto restante.
"""
from __future__ import annotations

import html as _html
import re

from lxml import etree, html as lhtml

#: Elementos que nunca contêm texto normativo.
_DESCARTAR = ("script", "style", "nav", "header", "footer", "noscript", "form", "button")


def _normalizar(texto: str) -> str:
    texto = _html.unescape(texto)
    texto = texto.replace("\xa0", " ").replace("​", "")
    texto = re.sub(r"[ \t]+", " ", texto)
    return texto.strip()


def _para_linhas(elemento) -> list[str]:
    """Converte um elemento em linhas, tratando <br> e blocos como quebras."""
    for ruim in elemento.xpath(".//" + " | .//".join(_DESCARTAR)):
        ruim.getparent().remove(ruim)

    bruto = lhtml.tostring(elemento, encoding="unicode")
    # <br> e o fim de cada bloco marcam quebra de linha; o resto das tags some.
    bruto = re.sub(r"(?i)<\s*br\s*/?>", "\n", bruto)
    bruto = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", bruto)
    bruto = re.sub(r"<[^>]+>", " ", bruto)

    linhas = [_normalizar(l) for l in bruto.split("\n")]
    return _separar_rotulos_colados(_juntar_rotulos_partidos([l for l in linhas if l]))


#: Rótulo de artigo que ficou sem a numeração, sozinho na linha.
_ROTULO_SOLTO = re.compile(r"^(?:Art|ART)(?:igo|IGO)?\s*\.?$")
#: Início da linha que traz a numeração que faltou ao rótulo.
_NUMERO_SOLTO = re.compile(r"^(?:\d|[ÚUúu]nico|[ÚU]NICO)")


def _juntar_rotulos_partidos(linhas: list[str]) -> list[str]:
    """Reúne o rótulo de artigo que a fonte partiu em duas linhas.

    Em parte do acervo o HTML traz uma quebra de linha no meio do rótulo —
    `Art. \\n\\n1º É denominada...` —, e ela chega aqui como duas linhas, "Art."
    e "1º É denominada...". Nenhuma das duas é rótulo, e o artigo se perderia.
    """
    juntas: list[str] = []
    for linha in linhas:
        if juntas and _ROTULO_SOLTO.match(juntas[-1]) and _NUMERO_SOLTO.match(linha):
            juntas[-1] = f"{juntas[-1]} {linha}"
        else:
            juntas.append(linha)
    return juntas


#: Fim de uma citação de alteração colado ao início do artigo seguinte.
#:
#: No acervo aparece como `.........." (NR) Art. 178. O Título...` numa só linha:
#: o preenchimento pontilhado substitui o trecho não alterado, as aspas fecham a
#: transcrição e o artigo da lei hospedeira começa ali mesmo, sem quebra no HTML.
#: O grupo capturado fica com o trecho da esquerda, a que pertence.
_COLADO = re.compile(r'((?:\.{5,}|["”»])\s*(?:\(NR\))?)\s+(?=Art\s*\.?\s*\d)')


def _separar_rotulos_colados(linhas: list[str]) -> list[str]:
    """Quebra a linha quando o rótulo de um artigo vem colado ao fim de uma citação.

    Sem esta separação o artigo se perderia: o fragmentador só reconhece rótulo
    no início da linha, e aqui ele está no meio.
    """
    separadas: list[str] = []
    for linha in linhas:
        partes = _COLADO.sub(lambda m: m.group(1) + "\n", linha).split("\n")
        separadas.extend(p.strip() for p in partes if p.strip())
    return separadas


def _texto_simples(elemento) -> str:
    return _normalizar(" ".join(elemento.itertext()))


class TextoExtraido:
    """Linhas do corpo da lei, mais os metadados que a página oferece."""

    def __init__(self, titulo: str = "", ementa: str = "", linhas: list[str] | None = None):
        self.titulo = titulo
        self.ementa = ementa
        self.linhas = linhas or []

    def __repr__(self) -> str:  # pragma: no cover - conveniência de depuração
        return f"TextoExtraido(titulo={self.titulo!r}, linhas={len(self.linhas)})"


#: Espécies normativas, para distinguir o título da lei do título do sítio.
_ESPECIE = re.compile(
    r"(?i)\b(lei|decreto|medida\s+provis[óo]ria|emenda|resolu[çc][ãa]o|portaria|"
    r"instru[çc][ãa]o\s+normativa)\b")


def _escolher_titulo(arvore) -> str:
    """Escolhe o cabeçalho que nomeia a norma.

    A página do Legin traz antes do conteúdo um `<h1>` com o nome da seção do
    sítio ("Legislação"). Pegar o primeiro `<h1>` devolveria esse. Por isso a
    escolha recai sobre o primeiro cabeçalho que nomeie uma espécie normativa.
    """
    candidatos: list[str] = []
    for xp in ('//div[@id="content"]//h1', '//h2[contains(@class,"documentFirstHeading")]',
               "//h1", "//h2", "//title"):
        for elemento in arvore.xpath(xp):
            texto = _texto_simples(elemento)
            if texto:
                candidatos.append(texto)

    for texto in candidatos:
        if _ESPECIE.search(texto) and any(c.isdigit() for c in texto):
            return texto
    return candidatos[0] if candidatos else ""


def extrair(html_bruto: str) -> TextoExtraido:
    """Extrai título, ementa e as linhas do corpo a partir do HTML."""
    arvore = lhtml.fromstring(html_bruto)

    titulo = _escolher_titulo(arvore)

    norma = arvore.xpath('//div[contains(@class,"textoNorma")]')
    if norma:
        return _extrair_legin(norma[0], titulo)
    return _extrair_generico(arvore, titulo)


def _extrair_legin(norma, titulo: str) -> TextoExtraido:
    ementa = ""
    achados = norma.xpath('.//*[contains(@class,"ementa")]')
    if achados:
        ementa = _texto_simples(achados[0])
        achados[0].getparent().remove(achados[0])

    corpos = norma.xpath('.//div[contains(@class,"texto")]')
    alvo = corpos[0] if corpos else norma
    return TextoExtraido(titulo=titulo, ementa=ementa, linhas=_para_linhas(alvo))


def _extrair_generico(arvore, titulo: str) -> TextoExtraido:
    """Escolhe o maior bloco de texto da página, descontado o ruído.

    Serve a páginas fora do padrão Legin. A heurística é grosseira de propósito:
    em página de lei, o corpo normativo é, com folga, o maior bloco contínuo.
    """
    candidatos = arvore.xpath("//article | //main | //div | //body")
    melhor, melhor_tamanho = None, 0
    for c in candidatos:
        tamanho = len(_texto_simples(c))
        # Prefere o menor contêiner que ainda concentre o texto: percorrendo do
        # mais externo ao mais interno, só troca quando o ganho é real.
        if tamanho > melhor_tamanho * 1.05:
            melhor, melhor_tamanho = c, tamanho
    if melhor is None:
        return TextoExtraido(titulo=titulo, linhas=[])
    return TextoExtraido(titulo=titulo, linhas=_para_linhas(melhor))
