"""Estruturas de uma lei e o seu encaixe hierárquico.

A hierarquia segue a Lei Complementar 95/1998, que fixa a articulação do texto
normativo: a unidade básica é o artigo; o artigo desdobra-se em parágrafos e
incisos; o inciso, em alíneas; a alínea, em itens. Acima do artigo ficam os
agrupadores — parte, livro, título, capítulo, seção e subseção —, que organizam
o texto sem conter comando próprio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tipo(str, Enum):
    """Tipos de fragmento reconhecidos."""

    PARTE = "parte"
    LIVRO = "livro"
    TITULO = "titulo"
    CAPITULO = "capitulo"
    SECAO = "secao"
    SUBSECAO = "subsecao"
    ARTIGO = "artigo"
    PARAGRAFO = "paragrafo"
    INCISO = "inciso"
    ALINEA = "alinea"
    ITEM = "item"
    EMENTA = "ementa"
    PREAMBULO = "preambulo"
    FECHO = "fecho"


#: Profundidade de cada tipo. Quanto maior, mais fundo na árvore.
#:
#: É o que permite decidir o pai de um fragmento sem conhecer o anterior: ao
#: encontrar um fragmento de nível N, desempilham-se os abertos de nível >= N, e
#: o que restar no topo é o pai. Daí o inciso (9) pender ora do artigo (7), ora
#: do parágrafo (8), conforme o que estiver aberto — exatamente como na lei.
NIVEL: dict[Tipo, int] = {
    Tipo.PARTE: 1,
    Tipo.LIVRO: 2,
    Tipo.TITULO: 3,
    Tipo.CAPITULO: 4,
    Tipo.SECAO: 5,
    Tipo.SUBSECAO: 6,
    Tipo.ARTIGO: 7,
    Tipo.PARAGRAFO: 8,
    Tipo.INCISO: 9,
    Tipo.ALINEA: 10,
    Tipo.ITEM: 11,
}

#: Fragmentos de contexto: não entram na árvore de dispositivos.
AVULSOS = {Tipo.EMENTA, Tipo.PREAMBULO, Tipo.FECHO}


@dataclass
class Fragmento:
    """Um dispositivo da lei, com o seu texto e os seus filhos."""

    tipo: Tipo
    #: Numeração como aparece no texto: "1º", "II", "a", "único".
    numero: str | None = None
    #: Texto do próprio fragmento, já sem o rótulo. No artigo, é o caput.
    texto: str = ""
    #: Rubrica dos agrupadores ("DAS DISPOSIÇÕES GERAIS").
    rubrica: str | None = None
    filhos: list["Fragmento"] = field(default_factory=list)
    #: Linha de origem no texto extraído, para conferência.
    linha: int | None = None

    @property
    def nivel(self) -> int:
        return NIVEL.get(self.tipo, 99)

    @property
    def rotulo(self) -> str:
        """Como o dispositivo é citado — 'Art. 5º', '§ 1º', 'II', 'a)'."""
        if self.tipo is Tipo.ARTIGO:
            return f"Art. {self.numero}"
        if self.tipo is Tipo.PARAGRAFO:
            return "Parágrafo único" if self.numero == "único" else f"§ {self.numero}"
        if self.tipo is Tipo.INCISO:
            return f"{self.numero}"
        if self.tipo is Tipo.ALINEA:
            return f"{self.numero})"
        if self.tipo is Tipo.ITEM:
            return f"{self.numero}."
        if self.numero:
            return f"{self.tipo.value.upper()} {self.numero}"
        return self.tipo.value.upper()

    def caminho(self, ate: "Fragmento | None" = None) -> str:
        """Rótulo acumulado desde a raiz, já montado pelo fragmentador."""
        return self._caminho or self.rotulo

    _caminho: str = field(default="", repr=False, compare=False)

    def percorrer(self):
        """Gera este fragmento e todos os descendentes, em pré-ordem."""
        yield self
        for filho in self.filhos:
            yield from filho.percorrer()

    def para_dicionario(self) -> dict:
        d: dict = {
            "tipo": self.tipo.value,
            "numero": self.numero,
            "rotulo": self.rotulo,
            "caminho": self._caminho or self.rotulo,
            "texto": self.texto,
        }
        if self.rubrica:
            d["rubrica"] = self.rubrica
        if self.linha is not None:
            d["linha"] = self.linha
        if self.filhos:
            d["filhos"] = [f.para_dicionario() for f in self.filhos]
        return d


@dataclass
class Lei:
    """Resultado da fragmentação: metadados e a árvore de dispositivos."""

    titulo: str = ""
    ementa: str = ""
    preambulo: str = ""
    fecho: str = ""
    origem: str = ""
    dispositivos: list[Fragmento] = field(default_factory=list)

    def percorrer(self):
        for d in self.dispositivos:
            yield from d.percorrer()

    def por_tipo(self, tipo: Tipo) -> list[Fragmento]:
        return [f for f in self.percorrer() if f.tipo is tipo]

    def contagem(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for f in self.percorrer():
            contagem[f.tipo.value] = contagem.get(f.tipo.value, 0) + 1
        return dict(sorted(contagem.items()))

    def para_dicionario(self) -> dict:
        return {
            "titulo": self.titulo,
            "ementa": self.ementa,
            "preambulo": self.preambulo,
            "fecho": self.fecho,
            "origem": self.origem,
            "contagem": self.contagem(),
            "dispositivos": [d.para_dicionario() for d in self.dispositivos],
        }
