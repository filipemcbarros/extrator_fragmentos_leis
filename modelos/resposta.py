"""Da resposta do modelo para um JSON no formato do fragmentador.

O modelo devolve só o essencial — tipo, numeração, texto e filhos. Rótulo,
caminho e contagem são derivados aqui, pelas mesmas classes que o regex usa, de
modo que os dois JSONs saem com as mesmas chaves e podem ser comparados campo a
campo. A hierarquia não é corrigida: fica como o modelo a montou. A exceção é a
emenda entre os trechos de uma lei longa — ver `_emendar`.
"""
from __future__ import annotations

import json
import re
import unicodedata

from fragmentador.modelos import NIVEL, Fragmento, Lei, Tipo
from fragmentador.rotulos import _limpar_numero

#: Rótulo que o modelo às vezes repete dentro de "numero" ("Art. 1º", "§ 2º").
_ROTULO = re.compile(
    r"^(?:art(?:igo)?\s*\.?|§|par[áa]grafo|inciso|al[íi]nea|item|parte|livro|"
    r"t[íi]tulo|cap[íi]tulo|subse[çc][ãa]o|se[çc][ãa]o)\s*(?=\S)", re.I)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))


def _texto(valor) -> str:
    return " ".join(valor.split()) if isinstance(valor, str) else ""


# --- leitura da resposta -----------------------------------------------------

def extrair_json(resposta: str) -> tuple[dict | None, str]:
    """Localiza o objeto JSON na resposta. Devolve (objeto, estado).

    O estado é "ok", "reparado" — a resposta foi cortada pelo limite de tokens
    e aproveitou-se o que estava completo — ou "invalido".
    """
    inicio = resposta.find("{")
    if inicio < 0:
        return None, "invalido"
    texto = resposta[inicio:]
    try:
        # raw_decode ignora o que vier depois do objeto: cerca de código, despedida.
        objeto, _ = json.JSONDecoder().raw_decode(texto)
        estado = "ok"
    except json.JSONDecodeError:
        objeto, estado = _reparar(texto), "reparado"
    if not isinstance(objeto, dict):
        return None, "invalido"
    return objeto, estado


#: Linha que os notebooks põem, no arquivo bruto da lei dividida, antes da
#: resposta de cada trecho.
_MARCA_DE_TRECHO = re.compile(r"^===== trecho \d+ de \d+ =====\n", re.M)


def separar_trechos(bruto: str) -> list[str]:
    """As respostas dos trechos de uma lei dividida; a da lei inteira sai sozinha."""
    partes = _MARCA_DE_TRECHO.split(bruto)
    return partes[1:] if len(partes) > 1 else [bruto]


def _reparar(texto: str):
    """Recupera um JSON truncado: corta no último objeto completo e fecha o resto."""
    cortes: list[tuple[int, str]] = []   # (posição após um '}', o que falta fechar)
    pilha: list[str] = []
    em_texto = escape = False
    for i, c in enumerate(texto):
        if em_texto:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                em_texto = False
        elif c == '"':
            em_texto = True
        elif c in "{[":
            pilha.append("}" if c == "{" else "]")
        elif c in "}]":
            if not pilha or pilha.pop() != c:
                break
            if c == "}":
                cortes.append((i + 1, "".join(reversed(pilha))))

    for posicao, fechos in reversed(cortes[-50:]):
        try:
            return json.loads(texto[:posicao] + fechos)
        except json.JSONDecodeError:
            continue
    return None


# --- normalização ------------------------------------------------------------

def _tipo(valor) -> Tipo | None:
    if not isinstance(valor, str):
        return None
    try:
        tipo = Tipo(_sem_acento(valor).strip().lower())
    except ValueError:
        return None
    return tipo if tipo in NIVEL else None


def _numero(valor) -> str | None:
    if valor is None:
        return None
    numero = _ROTULO.sub("", str(valor).strip()).rstrip(" ).-–—")
    if _sem_acento(numero).lower() == "unico":
        return "único"
    return _limpar_numero(numero) or None


def _construir(nos, destino: list[Fragmento]) -> int:
    """Converte os nós da resposta em fragmentos. Devolve o número de avisos.

    Há aviso para o nó que não é objeto ou traz tipo desconhecido. Ele é
    descartado, e os filhos sobem para o pai dele, para que o texto não se perca.
    """
    if not isinstance(nos, list):
        return int(nos is not None)
    avisos = 0
    for no in nos:
        if not isinstance(no, dict):
            avisos += 1
            continue
        tipo = _tipo(no.get("tipo"))
        if tipo is None:
            avisos += 1 + _construir(no.get("filhos"), destino)
            continue
        fragmento = Fragmento(tipo=tipo, numero=_numero(no.get("numero")),
                              texto=_texto(no.get("texto")),
                              rubrica=_texto(no.get("rubrica")) or None)
        destino.append(fragmento)
        avisos += _construir(no.get("filhos"), fragmento.filhos)
    return avisos


def _espinha(lei: Lei) -> list[Fragmento]:
    """Os dispositivos ainda abertos: o último de cada nível, da raiz ao mais fundo."""
    espinha: list[Fragmento] = []
    nos = lei.dispositivos
    while nos:
        espinha.append(nos[-1])
        nos = nos[-1].filhos
    return espinha


def _emendar(lei: Lei, raizes: list[Fragmento], continuacao: str) -> None:
    """Liga à árvore os dispositivos de um trecho seguinte.

    Dentro do trecho vale a hierarquia que o modelo montou. Só na emenda, onde
    ele não tinha como ver o pai, o encaixe é feito pelo nível do tipo — a mesma
    regra de pilha do fragmentador.
    """
    if continuacao and lei.dispositivos:
        ultimo = _espinha(lei)[-1]
        ultimo.texto = f"{ultimo.texto} {continuacao}".strip()
    for fragmento in raizes:
        espinha = _espinha(lei)
        while espinha and espinha[-1].nivel >= fragmento.nivel:
            espinha.pop()
        (espinha[-1].filhos if espinha else lei.dispositivos).append(fragmento)


def _caminhar(fragmentos: list[Fragmento], prefixo: str) -> None:
    for fragmento in fragmentos:
        fragmento._caminho = f"{prefixo}, {fragmento.rotulo}" if prefixo else fragmento.rotulo
        _caminhar(fragmento.filhos, fragmento._caminho)


def normalizar(resposta: dict | list[dict | None], origem: str = "",
               norma: str = "") -> tuple[dict, int]:
    """Converte a resposta em dicionário igual ao de `Lei.para_dicionario`.

    `resposta` é o objeto devolvido pelo modelo ou, na lei dividida, a lista dos
    objetos de cada trecho, na ordem; o trecho sem JSON aproveitável vem como
    None. Devolve também o número de avisos (ver `_construir`).
    """
    trechos = [resposta] if isinstance(resposta, dict) else resposta
    lei = Lei(origem=origem)
    avisos = 0
    for indice, objeto in enumerate(trechos):
        if objeto is None:
            continue
        for campo in ("titulo", "ementa", "preambulo"):
            if not getattr(lei, campo):
                setattr(lei, campo, _texto(objeto.get(campo)))
        lei.fecho = _texto(objeto.get("fecho")) or lei.fecho

        raizes: list[Fragmento] = []
        avisos += _construir(objeto.get("dispositivos"), raizes)
        if indice == 0:
            lei.dispositivos.extend(raizes)
        else:
            _emendar(lei, raizes, _texto(objeto.get("continuacao")))

    _caminhar(lei.dispositivos, "")
    dados = lei.para_dicionario()
    dados["norma"] = norma
    return dados, avisos
