"""Compara as respostas dos modelos com o JSON do regex, lei a lei.

Lê as pastas gravadas pelos notebooks (os de `notebooks/`), baixadas
do Drive para `modelos/resultados/`. Cada pasta é uma rodada — um modelo num
modo, restrito ou livre — com `bruto/`, `json/` e `registro.csv`. As rodadas
ficam em três grupos: `acervo/` (as restritas, sobre o acervo), `amostra/` (as
livres, sobre a amostra de 300 leis) e `testes/` (T4 e gramática sem espaços).
Compara-se um grupo por vez; as tabelas saem em `comparacao/`, dentro dele.

O regex é a referência, não um gabarito: as medidas dizem o quanto o modelo
concorda com ele. Onde discordam, quem errou só se sabe abrindo a lei.

Cada lei é reduzida à lista dos seus dispositivos, e a comparação tem quatro
partes:

- identificação — o modelo achou os mesmos dispositivos? Compara (tipo, número),
  sem olhar de quem cada um pende;
- hierarquia — e os pendurou no mesmo lugar? Compara o caminho inteiro
  ("CAPITULO I, Art. 1º, § 3º, I");
- texto — nos dispositivos de mesmo caminho, o texto é o mesmo?
- fidelidade — o texto de cada dispositivo do modelo está na lei? Esta parte não
  depende do regex: confronta a resposta com o texto da página.

A resposta sem JSON válido conta como zero. As médias saem das leis que todas
as rodadas comparadas responderam, para que nenhuma seja medida num conjunto
mais fácil que o das outras.

    python -m modelos.comparar
    python -m modelos.comparar --resultados modelos/resultados/amostra
"""
from __future__ import annotations

import argparse
import csv
import difflib
import fnmatch
import json
import pathlib
import re
from collections import Counter

from fragmentador.extracao import extrair
from fragmentador.fonte import ler
from fragmentador.modelos import NIVEL, Tipo

from .resposta import extrair_json, normalizar, separar_trechos

CAMPOS = ("titulo", "ementa", "preambulo", "fecho")

#: Agrupadores não têm texto próprio: a falta dele não é dispositivo vazio.
_AGRUPADORES = {t.value for t in NIVEL if NIVEL[t] < NIVEL[Tipo.ARTIGO]}


def _chave(texto: str | None) -> str:
    return " ".join((texto or "").replace("°", "º").split()).casefold()


def achatar(lei: dict) -> list[dict]:
    """Dispositivos da lei em pré-ordem, sem a árvore."""
    plano: list[dict] = []

    def descer(nos: list[dict]) -> None:
        for no in nos:
            plano.append({
                "tipo": no["tipo"],
                "id": (no["tipo"], _chave(no.get("numero"))),
                "caminho": _chave(no["caminho"]),
                # A rubrica entra no texto: quem a deixou no texto do agrupador
                # não errou o conteúdo, só a chave.
                "texto": " ".join(f"{no.get('rubrica') or ''} {no.get('texto') or ''}".split()),
            })
            descer(no.get("filhos", []))

    descer(lei.get("dispositivos", []))
    return plano


def _prf(comuns: int, do_modelo: int, do_regex: int) -> tuple[float, float, float]:
    """Precisão, revocação e F1. Dois conjuntos vazios concordam por inteiro."""
    if not do_modelo and not do_regex:
        return 1.0, 1.0, 1.0
    p = comuns / do_modelo if do_modelo else 0.0
    r = comuns / do_regex if do_regex else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _semelhanca(a: str, b: str) -> float:
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def _por_tipo(do_regex: list[dict], do_modelo: list[dict], nome: str) -> dict[str, list[int]]:
    """tipo -> [em comum, do modelo, do regex], casando por `nome` ("id" ou "caminho")."""
    r = Counter((d["tipo"], d[nome]) for d in do_regex)
    m = Counter((d["tipo"], d[nome]) for d in do_modelo)
    por_tipo: dict[str, list[int]] = {}
    for i, contagem in enumerate((r & m, m, r)):
        for (tipo, _), n in contagem.items():
            por_tipo.setdefault(tipo, [0, 0, 0])[i] += n
    return por_tipo


def comparar_lei(regex: dict, modelo: dict | None) -> dict:
    """Medidas de uma lei. `modelo` é None quando o JSON saiu inválido."""
    do_regex = achatar(regex)
    do_modelo = achatar(modelo) if modelo else []

    medidas: dict = {"dispositivos_regex": len(do_regex), "dispositivos_modelo": len(do_modelo)}
    for nome in ("id", "caminho"):
        r = Counter(d[nome] for d in do_regex)
        m = Counter(d[nome] for d in do_modelo)
        p, rev, f1 = _prf(sum((r & m).values()), len(do_modelo), len(do_regex))
        medidas[f"{nome}_p"], medidas[f"{nome}_r"], medidas[f"{nome}_f1"] = p, rev, f1

    # Por tipo, pelo caminho: é a medida que cobra a hierarquia.
    medidas["por_tipo"] = _por_tipo(do_regex, do_modelo, "caminho")
    medidas["por_tipo_id"] = _por_tipo(do_regex, do_modelo, "id")

    # Texto: pareia, na ordem, os dispositivos de mesmo caminho.
    textos_modelo: dict[str, list[str]] = {}
    for d in do_modelo:
        textos_modelo.setdefault(d["caminho"], []).append(d["texto"])
    semelhancas = []
    for d in do_regex:
        fila = textos_modelo.get(d["caminho"])
        if fila:
            semelhancas.append(_semelhanca(d["texto"], fila.pop(0)))
    medidas["pareados"] = len(semelhancas)
    medidas["texto_semelhanca"] = sum(semelhancas) / len(semelhancas) if semelhancas else 0.0
    medidas["texto_exato"] = (sum(1 for s in semelhancas if s == 1.0) / len(semelhancas)
                              if semelhancas else 0.0)

    for campo in CAMPOS:
        a, b = " ".join(regex.get(campo, "").split()), " ".join((modelo or {}).get(campo, "").split())
        medidas[f"{campo}_igual"] = int(modelo is not None and a == b)

    # Árvore idêntica: mesmos dispositivos, nos mesmos lugares, com o mesmo texto.
    medidas["identica"] = int(medidas["caminho_f1"] == 1.0 and bool(do_regex)
                              and medidas["texto_exato"] == 1.0)
    return medidas


# --- fidelidade ao texto da lei ----------------------------------------------

def _palavras(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.casefold())


def _trincas(palavras: list[str]) -> set[tuple[str, ...]]:
    return {tuple(palavras[i:i + 3]) for i in range(len(palavras) - 2)}


def fidelidade(lei: dict | None, fonte: str) -> dict:
    """Confronta o texto de cada dispositivo com o texto da página da lei.

    - literal: o texto aparece na lei tal como está, salvo espaços;
    - alheio: menos da metade das suas sequências de três palavras está na lei —
      é conteúdo que não veio dela (por exemplo, copiado do exemplo do prompt).
      Entre um e outro fica o texto alterado: da lei, mas com palavras trocadas;
    - vazio: dispositivo sem texto que não é agrupador.
    """
    fonte = " ".join(fonte.split())
    palavras_da_fonte = _palavras(fonte)
    trincas_da_fonte = _trincas(palavras_da_fonte)
    fonte_minuscula = " ".join(palavras_da_fonte)

    contagem = {"com_texto": 0, "literais": 0, "alheios": 0, "vazios": 0}

    def descer(nos: list[dict]) -> None:
        for no in nos:
            texto = " ".join((no.get("texto") or "").split())
            if not texto:
                contagem["vazios"] += no["tipo"] not in _AGRUPADORES
            else:
                contagem["com_texto"] += 1
                contagem["literais"] += texto in fonte
                palavras = _palavras(texto)
                trincas = _trincas(palavras)
                if trincas:
                    contagem["alheios"] += len(trincas & trincas_da_fonte) < len(trincas) / 2
                else:
                    contagem["alheios"] += " ".join(palavras) not in fonte_minuscula
            descer(no.get("filhos", []))

    descer((lei or {}).get("dispositivos", []))
    return contagem


# --- leitura das pastas ------------------------------------------------------

def ler_rodada(pasta: pathlib.Path) -> dict[str, dict]:
    """Uma entrada por lei respondida: ano, tokens, se foi cortada, se o JSON é válido."""
    anos = {p.stem: p.parent.name for p in (pasta / "bruto").glob("*/*.txt")}
    leis: dict[str, dict] = {}
    with (pasta / "registro.csv").open(encoding="utf-8", newline="") as f:
        # Depois das quatro colunas, a lei dividida traz o número de trechos e de válidos.
        for slug, tokens, cortada, valido, *_ in csv.reader(f):
            if slug in anos:   # vale a última linha de cada lei
                leis[slug] = {"ano": anos[slug], "tokens": int(tokens),
                              "cortada": cortada == "1", "valido": valido == "1"}
    return leis


def _ler_resposta(pasta: pathlib.Path, slug: str, lei: dict, regex: dict):
    """Devolve (resposta normalizada ou None, a mesma com reparo, tipos fora da lista)."""
    origem, norma = regex.get("origem", ""), regex.get("norma", "")
    if lei["valido"]:
        bruto = json.loads((pasta / "json" / lei["ano"] / f"{slug}.json").read_text(encoding="utf-8"))
        normal, avisos = normalizar(bruto, origem, norma)
        return normal, normal, avisos
    # Resposta cortada ou malformada: o reparo aproveita o que estava completo.
    texto = (pasta / "bruto" / lei["ano"] / f"{slug}.txt").read_text(encoding="utf-8")
    # Na lei dividida, cada trecho é reparado à parte; o que não se aproveita fica de fora.
    objetos = [extrair_json(trecho)[0] for trecho in separar_trechos(texto)]
    if all(objeto is None for objeto in objetos):
        return None, None, 0
    reparada = normalizar(objetos[0] if len(objetos) == 1 else objetos, origem, norma)[0]
    return None, reparada, 0


def _media(valores) -> float:
    valores = list(valores)
    return sum(valores) / len(valores) if valores else 0.0


def comparar(resultados: str = "modelos/resultados/acervo", coleta: str = "coleta",
             rodadas: list[str] | None = None, log=print) -> list[dict]:
    raiz = pathlib.Path(resultados)
    padroes = rodadas or ["*_oficial_*"]
    pastas = sorted(p.parent for p in raiz.glob("*/registro.csv")
                    if any(fnmatch.fnmatch(p.parent.name, padrao) for padrao in padroes))
    if not pastas:
        raise SystemExit(f"Nenhuma rodada em {raiz} casa com {padroes}.")

    leis = {p.name: ler_rodada(p) for p in pastas}
    comuns = sorted(set.intersection(*(set(l) for l in leis.values())))
    ano_de = {slug: leis[pastas[0].name][slug]["ano"] for slug in comuns}

    por_lei: list[dict] = []
    tipos: dict[str, dict[str, dict[str, list[int]]]] = {p.name: {"caminho": {}, "id": {}} for p in pastas}
    controle = {"com_texto": 0, "literais": 0, "alheios": 0, "vazios": 0}

    for slug in comuns:
        base = pathlib.Path(coleta) / ano_de[slug]
        regex = json.loads((base / "json" / f"{slug}.json").read_text(encoding="utf-8"))
        pagina = extrair(ler(base / "html" / f"{slug}.html"))
        fonte = " ".join([pagina.titulo, pagina.ementa, *pagina.linhas])
        # O regex passa pela mesma régua de fidelidade: é o controle da medida.
        for chave, n in fidelidade(regex, fonte).items():
            controle[chave] += n

        for pasta in pastas:
            lei = leis[pasta.name][slug]
            normal, reparada, tipos_invalidos = _ler_resposta(pasta, slug, lei, regex)
            medidas = comparar_lei(regex, normal)
            for nome, chave in (("caminho", "por_tipo"), ("id", "por_tipo_id")):
                for tipo, parcelas in medidas.pop(chave).items():
                    soma = tipos[pasta.name][nome].setdefault(tipo, [0, 0, 0])
                    for i, parcela in enumerate(parcelas):
                        soma[i] += parcela
            com_reparo = medidas if normal is not None else comparar_lei(regex, reparada)
            por_lei.append({
                "rodada": pasta.name, "ano": lei["ano"], "slug": slug,
                "valido": int(lei["valido"]), "cortada": int(lei["cortada"]), "tokens": lei["tokens"],
                "tipos_invalidos": tipos_invalidos,
                **{k: round(v, 4) if isinstance(v, float) else v for k, v in medidas.items()},
                "id_f1_reparo": round(com_reparo["id_f1"], 4),
                "caminho_f1_reparo": round(com_reparo["caminho_f1"], 4),
                **fidelidade(normal, fonte),
            })

    resumo: list[dict] = []
    for pasta in pastas:
        linhas = [l for l in por_lei if l["rodada"] == pasta.name]
        validas = [l for l in linhas if l["valido"]]
        com_texto = sum(l["com_texto"] for l in linhas) or 1
        dispositivos = sum(l["dispositivos_modelo"] for l in linhas) or 1
        resumo.append({
            "rodada": pasta.name,
            "leis_respondidas": len(leis[pasta.name]),
            "leis_comparadas": len(linhas),
            "json_valido_%": round(100 * _media(l["valido"] for l in linhas), 1),
            "cortadas_%": round(100 * _media(l["cortada"] for l in linhas), 1),
            "identificacao_f1": round(_media(l["id_f1"] for l in linhas), 4),
            "hierarquia_f1": round(_media(l["caminho_f1"] for l in linhas), 4),
            "arvore_identica_%": round(100 * _media(l["identica"] for l in linhas), 1),
            "identificacao_f1_validas": round(_media(l["id_f1"] for l in validas), 4),
            "hierarquia_f1_validas": round(_media(l["caminho_f1"] for l in validas), 4),
            "texto_semelhanca_validas": round(_media(l["texto_semelhanca"] for l in validas), 4),
            "texto_exato_validas": round(_media(l["texto_exato"] for l in validas), 4),
            "identificacao_f1_reparo": round(_media(l["id_f1_reparo"] for l in linhas), 4),
            "hierarquia_f1_reparo": round(_media(l["caminho_f1_reparo"] for l in linhas), 4),
            **{f"{c}_igual_%": round(100 * _media(l[f"{c}_igual"] for l in validas), 1) for c in CAMPOS},
            "dispositivos_no_regex": sum(l["dispositivos_regex"] for l in linhas),
            "dispositivos_no_modelo": sum(l["dispositivos_modelo"] for l in linhas),
            "texto_literal_%": round(100 * sum(l["literais"] for l in linhas) / com_texto, 1),
            "texto_alheio_%": round(100 * sum(l["alheios"] for l in linhas) / com_texto, 2),
            "dispositivos_vazios_%": round(100 * sum(l["vazios"] for l in linhas) / dispositivos, 2),
            "tipos_fora_da_lista": sum(l["tipos_invalidos"] for l in linhas),
        })

    por_tipo: list[dict] = []
    for pasta in pastas:
        for tipo in sorted(tipos[pasta.name]["caminho"], key=lambda t: NIVEL[Tipo(t)]):
            c, dm, dr = tipos[pasta.name]["caminho"][tipo]
            ci = tipos[pasta.name]["id"][tipo][0]
            p, r, f1 = _prf(c, dm, dr)
            pi, ri, f1i = _prf(ci, dm, dr)
            por_tipo.append({"rodada": pasta.name, "tipo": tipo, "no_regex": dr, "no_modelo": dm,
                             "identificacao_p": round(pi, 4), "identificacao_r": round(ri, 4),
                             "identificacao_f1": round(f1i, 4),
                             "hierarquia_p": round(p, 4), "hierarquia_r": round(r, 4),
                             "hierarquia_f1": round(f1, 4)})

    destino = raiz / "comparacao"
    destino.mkdir(parents=True, exist_ok=True)
    for nome, linhas in (("resumo", resumo), ("por_tipo", por_tipo), ("por_lei", por_lei)):
        with (destino / f"{nome}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(linhas[0]))
            escritor.writeheader()
            escritor.writerows(linhas)

    log(f"{len(comuns)} leis respondidas por todas as rodadas comparadas.\n")
    largura = max(len(r["rodada"]) for r in resumo) + 2
    log(" " * 28 + "".join(f"{r['rodada']:>{largura}s}" for r in resumo))
    for medida in list(resumo[0])[1:]:
        log(f"{medida:28s}" + "".join(f"{str(r[medida]):>{largura}s}" for r in resumo))
    total = controle["com_texto"] or 1
    log(f"\nControle da fidelidade (o próprio regex): {100 * controle['literais'] / total:.1f}% literal, "
        f"{100 * controle['alheios'] / total:.2f}% alheio.")
    log(f"Tabelas em {destino}: resumo.csv, por_tipo.csv, por_lei.csv")
    return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelos.comparar", description=__doc__.split("\n")[0])
    parser.add_argument("--resultados", default="modelos/resultados/acervo",
                        help="pasta do grupo de rodadas a comparar (acervo, amostra ou testes)")
    parser.add_argument("--coleta", default="coleta")
    parser.add_argument("--rodadas", nargs="*",
                        help='nomes ou padrões das pastas a comparar (padrão: "*_oficial_*")')
    args = parser.parse_args(argv)
    comparar(args.resultados, args.coleta, args.rodadas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
