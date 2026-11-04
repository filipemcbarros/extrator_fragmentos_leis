"""Estruturas de uma lei e o seu encaixe hierárquico.

A hierarquia segue a Lei Complementar 95/1998, que fixa a articulação do texto
normativo: a unidade básica é o artigo; o artigo desdobra-se em parágrafos e
incisos; o inciso, em alíneas; a alínea, em itens (art. 10, I e II). Acima do
artigo ficam os agrupadores — parte, livro, título, capítulo, seção e subseção
(art. 10, V) —, que organizam o texto sem conter comando próprio, e os
agrupamentos em Disposições Preliminares, Gerais, Finais ou Transitórias
(art. 10, VIII).

Os nomes seguem a LC 95/1998, sem acento: os tipos de dispositivo e, na lei, a
epígrafe (art. 4º), a ementa (art. 5º) e o preâmbulo (art. 6º). O fecho (local,
data e assinaturas) não é nomeado pela LC 95. Até a versão anterior a epígrafe
se chamava `titulo`; `Lei.titulo` continua como sinônimo, e `campo_da_lei` lê
os JSONs antigos.
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
    #: Agrupamento em Disposições Preliminares, Gerais, Finais ou Transitórias
    #: que não é rubrica de capítulo ou título (art. 10, VIII).
    DISPOSICOES = "disposicoes"
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
#: o que restar no topo é o pai. Daí o inciso (10) pender ora do artigo (8), ora
#: do parágrafo (9), conforme o que estiver aberto — exatamente como na lei.
#:
#: As disposições não têm lugar fixo: tomam o nível do agrupador que as precede
#: e ficam ao lado dele, ou abaixo dele quando ele acabou de abrir — ver
#: fragmentador. O nível da tabela vale quando não há agrupador aberto.
NIVEL: dict[Tipo, int] = {
    Tipo.PARTE: 1,
    Tipo.LIVRO: 2,
    Tipo.TITULO: 3,
    Tipo.CAPITULO: 4,
    Tipo.SECAO: 5,
    Tipo.SUBSECAO: 6,
    Tipo.DISPOSICOES: 7,
    Tipo.ARTIGO: 8,
    Tipo.PARAGRAFO: 9,
    Tipo.INCISO: 10,
    Tipo.ALINEA: 11,
    Tipo.ITEM: 12,
}

#: Fragmentos de contexto: não entram na árvore de dispositivos.
AVULSOS = {Tipo.EMENTA, Tipo.PREAMBULO, Tipo.FECHO}


@dataclass
class Fragmento:
    """Um dispositivo da lei, com o seu texto e os seus filhos."""

    tipo: Tipo
    #: Numeração como aparece no texto: "1º", "II", "a", "único". Nos vetos e
    #: revogações agrupados ("Arts. 5º a 7º (VETADOS)"), o intervalo: "5º a 7º".
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
        if self._nivel is not None:
            return self._nivel
        return NIVEL.get(self.tipo, 99)

    @property
    def agrupado(self) -> bool:
        """Rótulo que reúne vários dispositivos: 'Arts. 5º a 7º', '§§ 1º e 2º'."""
        return bool(self.numero) and any(s in self.numero for s in (",", " a ", " e ", " - "))

    @property
    def rotulo(self) -> str:
        """Como o dispositivo é citado — 'Art. 5º', '§ 1º', 'II', 'a)'."""
        if self.tipo is Tipo.ARTIGO:
            return f"{'Arts.' if self.agrupado else 'Art.'} {self.numero}"
        if self.tipo is Tipo.PARAGRAFO:
            if self.numero == "único":
                return "Parágrafo único"
            return f"{'§§' if self.agrupado else '§'} {self.numero}"
        if self.tipo is Tipo.DISPOSICOES:
            return self.rubrica or "DISPOSIÇÕES"
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
    #: Nível decidido pelo contexto, só nas disposições.
    _nivel: int | None = field(default=None, repr=False, compare=False)

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

    #: Epígrafe (LC 95/1998, art. 4º): "LEI Nº 8.666, DE 21 DE JUNHO DE 1993".
    epigrafe: str = ""
    ementa: str = ""
    preambulo: str = ""
    fecho: str = ""
    origem: str = ""
    dispositivos: list[Fragmento] = field(default_factory=list)

    @property
    def titulo(self) -> str:
        """Nome antigo da epígrafe, mantido para o código que ainda o usa."""
        return self.epigrafe

    @titulo.setter
    def titulo(self, valor: str) -> None:
        self.epigrafe = valor

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
            "epigrafe": self.epigrafe,
            "ementa": self.ementa,
            "preambulo": self.preambulo,
            "fecho": self.fecho,
            "origem": self.origem,
            "contagem": self.contagem(),
            "dispositivos": [d.para_dicionario() for d in self.dispositivos],
        }


#: Nomes antigos dos campos da lei, para ler JSONs gravados antes da mudança
#: (padrão-ouro e saídas dos modelos usam "titulo").
SINONIMOS = {"epigrafe": ("epigrafe", "titulo")}


def campo_da_lei(dados: dict | None, campo: str) -> str:
    """Lê um campo da lei num JSON novo ou antigo: 'epigrafe' também acha 'titulo'."""
    for nome in SINONIMOS.get(campo, (campo,)):
        valor = (dados or {}).get(nome)
        if valor:
            return valor
    return ""
