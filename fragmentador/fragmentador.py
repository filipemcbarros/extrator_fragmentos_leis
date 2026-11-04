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

#: Agrupadores: ficam acima do artigo e não têm comando próprio.
_AGRUPADORES = {t for t in NIVEL if NIVEL[t] < NIVEL[Tipo.ARTIGO]}

#: Abre o corpo da lei: antes disso vem o preâmbulo ("O PRESIDENTE DA REPÚBLICA…").
_TIPOS_DE_ABERTURA = _AGRUPADORES | {Tipo.ARTIGO}

#: Dispositivos que podem anunciar uma enumeração em itens. A LC 95/1998 só
#: prevê item sob alínea (art. 10, II); as leis anteriores a ela também
#: enumeram em algarismos arábicos sob inciso e parágrafo.
_PAIS_DE_ITEM = {Tipo.INCISO, Tipo.PARAGRAFO}


def fragmentar(texto: TextoExtraido, origem: str = "") -> Lei:
    """Monta a árvore de dispositivos a partir das linhas extraídas."""
    lei = Lei(epigrafe=texto.titulo, ementa=texto.ementa, origem=origem)

    pilha: list[Fragmento] = []
    preambulo: list[str] = []
    fecho: list[str] = []
    corpo_comecou = False
    no_fecho = False

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

        # O item só existe dentro de uma enumeração. Fora dela, "1." é
        # numeração corrente dentro do texto, ou linha de tabela.
        if reconhecido and reconhecido[0] is Tipo.ITEM and not _item_cabe(pilha, reconhecido[1]):
            reconhecido = None

        # "DISPOSIÇÕES GERAIS" logo abaixo de "CAPÍTULO I" é a rubrica dele, e
        # não um agrupamento à parte.
        if (reconhecido and reconhecido[0] is Tipo.DISPOSICOES
                and pilha and _sem_rubrica(pilha[-1])):
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
            if pilha and _sem_rubrica(pilha[-1]) and _rubrica_em_minusculas(linha):
                # Rubrica fora da caixa alta, comum nas leis antigas:
                # "Capítulo I" / "Da Definição de Microempresa".
                pilha[-1].rubrica = linha
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

        if tipo in _AGRUPADORES:
            # No agrupador, o que segue o rótulo na mesma linha é a rubrica.
            fragmento = Fragmento(tipo=tipo, numero=numero, rubrica=resto or None, linha=indice)
        else:
            fragmento = Fragmento(tipo=tipo, numero=numero, texto=resto, linha=indice)
        if tipo is Tipo.ARTIGO:
            # Num veto agrupado ("Arts. 5º a 7º"), vale o último da lista.
            base = _numero_final(numero)
            if base is not None:
                ultimo_artigo = base

        if tipo is Tipo.DISPOSICOES:
            fragmento._nivel = _nivel_das_disposicoes(pilha)
        nivel = fragmento.nivel
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


def _numero_final(numero: str | None) -> int | None:
    """Último inteiro da numeração: '5º a 7º' devolve 7; '5º-A' devolve 5."""
    if not numero:
        return None
    achados = re.findall(r"\d+", numero)
    return int(achados[-1]) if achados else None


def _item_cabe(pilha: list[Fragmento], numero: str | None) -> bool:
    """O item pode abrir aqui?

    Sob alínea, sempre, como prevê a LC 95/1998. Depois de outro item, só se a
    numeração continuar a dele. Sob inciso ou parágrafo, só como primeiro item
    de uma enumeração anunciada por dois-pontos ("…as seguintes multas:").
    """
    if not pilha:
        return False
    topo = pilha[-1]
    n = _numero_base(numero)
    if topo.tipo is Tipo.ALINEA:
        return True
    if topo.tipo is Tipo.ITEM:
        anterior = _numero_base(topo.numero)
        return n is not None and anterior is not None and n == anterior + 1
    if topo.tipo in _PAIS_DE_ITEM:
        return n == 1 and topo.texto.rstrip().endswith(":")
    return False


def _nivel_das_disposicoes(pilha: list[Fragmento]) -> int:
    """Nível do agrupamento em disposições (LC 95/1998, art. 10, VIII).

    Ele integra a mesma composição dos demais agrupadores: "DISPOSIÇÕES FINAIS"
    depois do Capítulo V é irmã dele, e não parte dele. A exceção é o agrupador
    que acabou de abrir, sem dispositivo algum — "TÍTULO II" / "DISPOSIÇÃO
    PRELIMINAR" / "Art. 4º" —, caso em que as disposições estão dentro dele.
    """
    abertos = [f for f in pilha if f.tipo in _AGRUPADORES]
    if not abertos:
        return NIVEL[Tipo.DISPOSICOES]
    ultimo = abertos[-1]
    if ultimo.filhos or ultimo.tipo is Tipo.DISPOSICOES:
        return ultimo.nivel
    return max(ultimo.nivel + 1, NIVEL[Tipo.DISPOSICOES])


def _sem_rubrica(fragmento: Fragmento) -> bool:
    """Agrupador recém-aberto, que ainda espera a rubrica na linha seguinte."""
    return (fragmento.tipo in _AGRUPADORES and fragmento.tipo is not Tipo.DISPOSICOES
            and not fragmento.rubrica and not fragmento.texto)


def _rubrica_em_minusculas(linha: str) -> bool:
    """Linha curta que nomeia o agrupador, sem ser caixa alta nem enumeração."""
    linha = linha.strip()
    return (0 < len(linha) <= 120 and linha[0].isupper() and not eh_rubrica(linha)
            and not linha.endswith((";", ",")))


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
    for fragmento in lei.percorrer():
        if fragmento.tipo not in _AGRUPADORES or not fragmento.texto:
            continue
        partes = fragmento.texto.split(" ")
        # A rubrica é a primeira sentença em caixa alta do texto acumulado.
        for corte in range(len(partes), 0, -1):
            candidata = " ".join(partes[:corte])
            if eh_rubrica(candidata):
                # A rubrica pode ter começado na linha do rótulo.
                fragmento.rubrica = (f"{fragmento.rubrica} {candidata}"
                                     if fragmento.rubrica else candidata)
                fragmento.texto = " ".join(partes[corte:]).strip()
                break


def fragmentar_html(html_bruto: str, origem: str = "") -> Lei:
    """Atalho: HTML cru em árvore de dispositivos."""
    return fragmentar(extrair(html_bruto), origem=origem)
