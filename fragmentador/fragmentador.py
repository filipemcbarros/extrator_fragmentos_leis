"""Das linhas de texto para a árvore de dispositivos.

O algoritmo é uma pilha. Cada linha ou abre um dispositivo novo — e aí o seu
nível diz de quem ele é filho — ou continua o texto do último dispositivo
aberto. É o que basta para reproduzir a articulação da lei, inclusive o caso em
que o mesmo tipo pende de pais diferentes: o inciso que vem logo após o caput é
filho do artigo; o que vem depois de um parágrafo é filho do parágrafo.
"""
from __future__ import annotations

import re

from .extracao import TextoExtraido, extrair
from .modelos import NIVEL, Fragmento, Lei, Tipo
from .rotulos import eh_fecho, eh_rubrica, reconhecer

#: Abertura de citação de alteração: a lei que altera outra transcreve o texto
#: alterado entre aspas. O transcrito é texto do artigo que promove a alteração,
#: e não dispositivo da lei que o contém — tratá-lo como dispositivo faria a Lei
#: 14.133/2021, por exemplo, "ganhar" os arts. 337-E a 337-P do Código Penal.
_ABRE_CITACAO = re.compile(r'^["“«]')
#: Fecho da citação, com ou sem a marca de nova redação.
_FECHA_CITACAO = re.compile(r'["”»]\s*(?:\(NR\))?\s*$')

#: Abre o corpo da lei: antes disso vem o preâmbulo ("O PRESIDENTE DA REPÚBLICA…").
_TIPOS_DE_ABERTURA = {
    Tipo.ARTIGO, Tipo.PARTE, Tipo.LIVRO, Tipo.TITULO,
    Tipo.CAPITULO, Tipo.SECAO, Tipo.SUBSECAO,
}


def fragmentar(texto: TextoExtraido, origem: str = "") -> Lei:
    """Monta a árvore de dispositivos a partir das linhas extraídas."""
    lei = Lei(titulo=texto.titulo, ementa=texto.ementa, origem=origem)

    pilha: list[Fragmento] = []
    preambulo: list[str] = []
    fecho: list[str] = []
    corpo_comecou = False
    no_fecho = False
    alinea_aberta = False

    em_citacao = False
    ultimo_artigo: int | None = None

    for indice, linha in enumerate(texto.linhas):
        if no_fecho:
            fecho.append(linha)
            continue

        abre = bool(_ABRE_CITACAO.match(linha))
        if em_citacao and not abre:
            # A citação também se encerra quando aparece o artigo seguinte da lei
            # hospedeira. É o caso em que a fonte não fecha as aspas e ainda cola
            # o rótulo ao fim do preenchimento pontilhado: a numeração contínua é
            # o único sinal confiável de que o texto voltou à lei que altera.
            if _retoma_sequencia(linha, ultimo_artigo):
                em_citacao = False
            else:
                # Dentro da citação nada é dispositivo: tudo é texto do artigo
                # que promove a alteração.
                if pilha:
                    _acrescentar_texto(pilha[-1], linha)
                if _FECHA_CITACAO.search(linha):
                    em_citacao = False
                continue
        if abre:
            # Uma nova abertura encerra a citação anterior: no acervo é comum o
            # bloco não trazer aspas de fechamento.
            em_citacao = not bool(_FECHA_CITACAO.search(linha[1:]))
            if pilha:
                _acrescentar_texto(pilha[-1], linha)
            continue

        reconhecido = reconhecer(linha)

        # O item só existe sob alínea. Fora desse contexto, "1." é numeração
        # corrente dentro do texto, e não um dispositivo.
        if reconhecido and reconhecido[0] is Tipo.ITEM and not alinea_aberta:
            reconhecido = None

        # Dispositivo aberto ainda sem texto não se fecha: quando a fonte põe o
        # rótulo sozinho na linha ("a)"), a seguinte é o texto dele, mesmo que
        # comece por algo que pareça rótulo de nível acima ("§ 1º do art. 2º;").
        if (reconhecido and pilha and not pilha[-1].texto
                and pilha[-1].nivel >= NIVEL[Tipo.ARTIGO]
                and NIVEL[reconhecido[0]] < pilha[-1].nivel):
            reconhecido = None

        if reconhecido is None:
            if not corpo_comecou:
                preambulo.append(linha)
                continue
            # O fecho encerra o corpo mesmo com dispositivo aberto: é o que vem
            # depois do último artigo, e sem isto a data e as assinaturas seriam
            # anexadas ao texto dele.
            if eh_fecho(linha):
                no_fecho = True
                fecho.append(linha)
                pilha.clear()
                continue
            if pilha:
                _acrescentar_texto(pilha[-1], linha)
            else:
                preambulo.append(linha)
            continue

        tipo, numero, resto = reconhecido

        if not corpo_comecou:
            if tipo not in _TIPOS_DE_ABERTURA:
                preambulo.append(linha)
                continue
            corpo_comecou = True

        fragmento = Fragmento(tipo=tipo, numero=numero, texto=resto, linha=indice)
        alinea_aberta = tipo is Tipo.ALINEA
        if tipo is Tipo.ARTIGO:
            base = _numero_base(numero)
            if base is not None:
                ultimo_artigo = base

        nivel = NIVEL[tipo]
        while pilha and pilha[-1].nivel >= nivel:
            pilha.pop()

        if pilha:
            pilha[-1].filhos.append(fragmento)
            fragmento._caminho = f"{pilha[-1]._caminho}, {fragmento.rotulo}"
        else:
            lei.dispositivos.append(fragmento)
            fragmento._caminho = fragmento.rotulo

        pilha.append(fragmento)

    _preencher_rubricas(lei, texto.linhas)

    lei.preambulo = " ".join(preambulo).strip()
    lei.fecho = " ".join(fecho).strip()
    return lei


def _numero_base(numero: str | None) -> int | None:
    """Parte inteira da numeração do artigo: '5º-A' devolve 5."""
    if not numero:
        return None
    m = re.match(r"(\d+)", numero)
    return int(m.group(1)) if m else None


def _retoma_sequencia(linha: str, ultimo_artigo: int | None) -> bool:
    """A linha abre o artigo imediatamente seguinte ao último da lei hospedeira?

    Serve para sair de uma citação que a fonte não fechou. Exige sucessão exata
    e numeração sem sufixo de letra: o artigo acrescentado por alteração — o
    '337-E' do Código Penal — nunca continua a sequência da lei que o insere.
    """
    if ultimo_artigo is None:
        return False
    reconhecido = reconhecer(linha)
    if not reconhecido or reconhecido[0] is not Tipo.ARTIGO:
        return False
    numero = reconhecido[1] or ""
    if re.search(r"-\s*[A-Z]$", numero):
        return False
    return _numero_base(numero) == ultimo_artigo + 1


def _acrescentar_texto(fragmento: Fragmento, linha: str) -> None:
    fragmento.texto = f"{fragmento.texto} {linha}".strip() if fragmento.texto else linha


def _preencher_rubricas(lei: Lei, linhas: list[str]) -> None:
    """Move para `rubrica` a linha em caixa alta que nomeia um agrupador.

    No Legin, "CAPÍTULO I" e "DAS DISPOSIÇÕES GERAIS" são linhas distintas: a
    segunda chega ao fragmento como texto, e é a rubrica dele.
    """
    agrupadores = {Tipo.PARTE, Tipo.LIVRO, Tipo.TITULO,
                   Tipo.CAPITULO, Tipo.SECAO, Tipo.SUBSECAO}
    for fragmento in lei.percorrer():
        if fragmento.tipo not in agrupadores or not fragmento.texto:
            continue
        partes = fragmento.texto.split(" ")
        # A rubrica é a primeira sentença em caixa alta do texto acumulado.
        for corte in range(len(partes), 0, -1):
            candidata = " ".join(partes[:corte])
            if eh_rubrica(candidata):
                fragmento.rubrica = candidata
                fragmento.texto = " ".join(partes[corte:]).strip()
                break


def fragmentar_html(html_bruto: str, origem: str = "") -> Lei:
    """Atalho: HTML cru em árvore de dispositivos."""
    return fragmentar(extrair(html_bruto), origem=origem)
