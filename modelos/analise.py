"""Tabelas que completam as de `comparar`: tamanho, época, cortes e custo.

Parte do que `comparar` gravou em `comparacao/por_lei.csv` e do que está em cada
rodada (`registro.csv`, `longas.txt`, `bruto/`, `json/`), e grava em `analise/`,
dentro do grupo de rodadas:

- `volume.csv` — por rodada, leis inteiras e divididas: pedidos, tokens,
  validade do JSON, tempo de geração, unidades de computação e custo;
- `cortes.csv` — como terminam as respostas cortadas pelo limite de tokens;
- `cortes_por_tamanho.csv` — fração de respostas cortadas por tamanho da lei;
- `por_tamanho.csv`, `por_dispositivos.csv`, `por_epoca.csv` — as medidas da
  comparação por faixa de tokens, de dispositivos no regex e de ano;
- `concordancia.csv` — em quantas leis a árvore de cada combinação de modelos
  é idêntica à do regex;
- `pendura.csv` — de que tipo de dispositivo cada tipo pende;
- `projecao.csv` — tempo e custo previstos para as leis que ficaram de fora.

O tempo de geração não está nos dados: sai da saída dos notebooks e é anotado à
mão em `tempos.csv`, na pasta do grupo (rodada, etapa, segundos, observação).
Sem esse arquivo, as colunas de tempo e custo ficam vazias.

O tamanho da lei em tokens é uma estimativa: o número de caracteres do trecho
que vai no prompt, dividido pela razão caracteres/token de cada modelo. A razão
sai da fronteira dos 3.000 tokens, que separa as leis enviadas inteiras das
demais.

    python -m modelos.comparar     # antes: grava comparacao/por_lei.csv
    python -m modelos.analise
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import pathlib
import re
from collections import Counter

from fragmentador.fonte import ler

from .entrada import preparar
from .resposta import normalizar, separar_trechos

#: Consumo da A100 de 40 GB no Colab Pro e preço do pacote avulso de 100 unidades.
UNIDADES_POR_HORA = 5.3
REAIS_POR_UNIDADE = 58 / 100

#: Acima disto a lei não foi enviada inteira (MAX_TOKENS_LEI da primeira etapa).
LIMITE_INTEIRA = 3000

#: Faixas (de, até), com o limite de cima fora da faixa; None = sem limite.
FAIXAS_TOKENS = [(0, 500), (500, 1000), (1000, 2000), (2000, 3000), (3000, 6000), (6000, None)]
#: Só leis inteiras. A última passa de 3.000 porque o tamanho é estimado.
FAIXAS_CORTE = [(0, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500), (2500, 3100)]
FAIXAS_DISPOSITIVOS = [(1, 3), (3, 6), (6, 11), (11, 31), (31, 101), (101, None)]
EPOCAS = [(1891, 1940), (1940, 1960), (1960, 1980), (1980, 2000), (2000, 2027)]


def _faixa(valor: float, faixas: list[tuple[int, int | None]]) -> tuple[int, int | None] | None:
    for de, ate in faixas:
        if valor >= de and (ate is None or valor < ate):
            return de, ate
    return None


def _rotulo(faixa: tuple[int, int | None]) -> str:
    de, ate = faixa
    return f"{de} ou mais" if ate is None else f"{de} a {ate - 1}"


# --- leitura -----------------------------------------------------------------

def ler_registro(pasta: pathlib.Path) -> dict[str, dict]:
    """Uma entrada por lei respondida; vale a última linha de cada uma."""
    anos = {p.stem: p.parent.name for p in (pasta / "bruto").glob("*/*.txt")}
    leis: dict[str, dict] = {}
    with (pasta / "registro.csv").open(encoding="utf-8", newline="") as f:
        for slug, tokens, cortada, valido, *resto in csv.reader(f):
            if slug in anos:
                trechos = int(resto[0]) if resto else 1
                leis[slug] = {"ano": anos[slug], "tokens": int(tokens), "cortada": cortada == "1",
                              "valido": valido == "1", "trechos": trechos, "dividida": trechos > 1,
                              "trechos_validos": int(resto[1]) if resto else int(valido)}
    return leis


def ler_tempos(grupo: pathlib.Path) -> dict[tuple[str, str], int]:
    """Segundos de geração por (rodada, etapa), somando as linhas de `tempos.csv`."""
    tempos: Counter = Counter()
    arquivo = grupo / "tempos.csv"
    if arquivo.exists():
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            for linha in csv.DictReader(f):
                tempos[linha["rodada"], linha["etapa"]] += int(linha["segundos"])
    return dict(tempos)


def tamanhos(coleta: pathlib.Path, destino: pathlib.Path) -> dict[str, int]:
    """Caracteres do trecho de cada lei que vai no prompt. Guardado em `tamanhos.csv`."""
    arquivo = destino / "tamanhos.csv"
    if arquivo.exists():
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            return {linha["slug"]: int(linha["caracteres"]) for linha in csv.DictReader(f)}
    caracteres = {a.stem: len(preparar(ler(a))) for a in sorted(coleta.glob("*/html/*.html"))}
    _gravar(destino, "tamanhos", [{"slug": s, "caracteres": n} for s, n in caracteres.items()])
    return caracteres


def calibrar(leis: dict[str, dict], longas: list[str], caracteres: dict[str, int]) -> float:
    """Caracteres por token do modelo, pela fronteira entre leis inteiras e as demais.

    Procura o número de caracteres que melhor separa as leis que o tokenizador
    do modelo contou até `LIMITE_INTEIRA` das que contou acima.
    """
    dentro = sorted(caracteres[s] for s, lei in leis.items() if not lei["dividida"])
    fora = sorted([caracteres[s] for s, lei in leis.items() if lei["dividida"]] + [caracteres[s] for s in longas])

    def erros(corte: int) -> int:
        return bisect.bisect_right(fora, corte) + len(dentro) - bisect.bisect_right(dentro, corte)

    return min(range(4000, 16000, 50), key=erros) / LIMITE_INTEIRA


# --- respostas cortadas ------------------------------------------------------

def classificar_corte(resposta: str) -> str | None:
    """Como termina a resposta sem JSON válido; None se o JSON é válido.

    Olha só o fim do texto, por padrões: as categorias menores são aproximadas.
    """
    try:
        json.JSONDecoder().raw_decode(resposta[resposta.index("{"):])
        return None
    except ValueError:
        pass
    fim = resposta[-600:]
    if re.search(r"[ \n\t]{200,}", fim):
        return "laço de espaços"
    if re.search(r"(?:\\[nt]|\\u00a0|\s){150,}", fim):
        return "laço dentro de um texto"
    if re.search(r"(.{1,60}?)\1{6,}", fim, re.S):
        return "repetição curta"
    # O penúltimo bloco de 150 caracteres já tinha aparecido antes na resposta.
    if resposta[:-150].count(resposta[-300:-150]) > 1:
        return "repetição de trecho longo"
    return "outro"


# --- medidas -----------------------------------------------------------------

def _medias(linhas: list[dict]) -> dict:
    """As medidas de `por_lei.csv`, em média sobre um conjunto de leis de uma rodada."""
    n = len(linhas) or 1
    return {
        "json_valido_%": round(100 * sum(l["valido"] == "1" for l in linhas) / n, 1),
        "identificacao_f1": round(sum(float(l["id_f1"]) for l in linhas) / n, 4),
        "hierarquia_f1": round(sum(float(l["caminho_f1"]) for l in linhas) / n, 4),
        "arvore_identica_%": round(100 * sum(l["identica"] == "1" for l in linhas) / n, 1),
        "identificacao_f1_reparo": round(sum(float(l["id_f1_reparo"]) for l in linhas) / n, 4),
        "hierarquia_f1_reparo": round(sum(float(l["caminho_f1_reparo"]) for l in linhas) / n, 4),
    }


def _por_faixa(por_lei: dict[str, dict[str, dict]], rodadas: list[str], faixas, valor) -> list[dict]:
    """Uma linha por faixa e rodada; `valor(slug)` dá a grandeza que define a faixa."""
    grupos: dict = {faixa: [] for faixa in faixas}
    for slug in por_lei:
        faixa = _faixa(valor(slug), faixas)
        if faixa is not None:
            grupos[faixa].append(slug)
    return [{"faixa": _rotulo(faixa), "leis": len(slugs), "rodada": rodada,
             **_medias([por_lei[s][rodada] for s in slugs])}
            for faixa, slugs in grupos.items() for rodada in rodadas]


def _pendura(lei: dict, conta: Counter) -> None:
    def descer(nos: list[dict], pai: str) -> None:
        for no in nos:
            conta[no["tipo"], pai] += 1
            descer(no.get("filhos", []), no["tipo"])

    descer(lei.get("dispositivos", []), "raiz")


def _gravar(destino: pathlib.Path, nome: str, linhas: list[dict]) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    with (destino / f"{nome}.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)


# --- análise -----------------------------------------------------------------

def analisar(resultados: str = "modelos/resultados/acervo", coleta: str = "coleta",
             regua: str = "qwen_oficial_restrita", log=print) -> None:
    grupo, coleta_ = pathlib.Path(resultados), pathlib.Path(coleta)
    destino = grupo / "analise"

    por_lei: dict[str, dict[str, dict]] = {}   # slug -> rodada -> linha de por_lei.csv
    arquivo = grupo / "comparacao" / "por_lei.csv"
    if not arquivo.exists():
        raise SystemExit(f"Falta {arquivo}: rode antes python -m modelos.comparar --resultados {resultados}")
    with arquivo.open(encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f):
            por_lei.setdefault(linha["slug"], {})[linha["rodada"]] = linha
    rodadas = sorted(next(iter(por_lei.values())))

    leis = {r: ler_registro(grupo / r) for r in rodadas}
    longas = {r: (grupo / r / "longas.txt").read_text().split() for r in rodadas}
    tempos = ler_tempos(grupo)
    caracteres = tamanhos(coleta_, destino)
    razao = {r: calibrar(leis[r], longas[r], caracteres) for r in rodadas}
    log("Caracteres por token: " + ", ".join(f"{r} {razao[r]:.2f}" for r in rodadas))

    # Volume, validade e custo; e os cortes, que pedem abrir as respostas inválidas.
    volume, cortes, cortes_tamanho = [], [], []
    for r in rodadas:
        tipos = {etapa: Counter() for etapa in ("inteiras", "divididas")}
        faixas = {faixa: [0, 0] for faixa in FAIXAS_CORTE}
        for slug, lei in leis[r].items():
            etapa = "divididas" if lei["dividida"] else "inteiras"
            if not lei["valido"]:
                bruto = (grupo / r / "bruto" / lei["ano"] / f"{slug}.txt").read_text(encoding="utf-8")
                tipos[etapa].update(filter(None, map(classificar_corte, separar_trechos(bruto))))
            if not lei["dividida"]:
                faixa = _faixa(caracteres[slug] / razao[r], FAIXAS_CORTE)
                if faixa is not None:
                    faixas[faixa][0] += 1
                    faixas[faixa][1] += lei["cortada"]
        for etapa in ("inteiras", "divididas"):
            conjunto = [lei for lei in leis[r].values() if lei["dividida"] == (etapa == "divididas")]
            if not conjunto:
                continue
            gerados = sum(lei["tokens"] for lei in conjunto)
            segundos = tempos.get((r, etapa))
            unidades = segundos / 3600 * UNIDADES_POR_HORA if segundos else None
            volume.append({
                "rodada": r, "leis": etapa, "n_leis": len(conjunto),
                "pedidos": sum(lei["trechos"] for lei in conjunto), "tokens_gerados": gerados,
                "json_valido": sum(lei["valido"] for lei in conjunto),
                "cortadas": sum(lei["cortada"] for lei in conjunto),
                "pedidos_validos": sum(lei["trechos_validos"] for lei in conjunto),
                "segundos": segundos or "", "tokens_por_segundo": round(gerados / segundos) if segundos else "",
                "unidades": round(unidades, 1) if segundos else "",
                "custo_reais": round(unidades * REAIS_POR_UNIDADE, 2) if segundos else "",
                "custo_por_mil_leis": round(1000 * unidades * REAIS_POR_UNIDADE / len(conjunto), 2) if segundos else "",
            })
            cortes += [{"rodada": r, "leis": etapa, "como_termina": tipo, "respostas": n}
                       for tipo, n in tipos[etapa].most_common()]
        cortes_tamanho += [{"rodada": r, "tokens_da_lei": _rotulo(faixa), "leis": n, "cortadas": c,
                            "cortadas_%": round(100 * c / (n or 1), 1)} for faixa, (n, c) in faixas.items()]
    _gravar(destino, "volume", volume)
    _gravar(destino, "cortes", cortes or [{"rodada": "", "leis": "", "como_termina": "", "respostas": 0}])
    _gravar(destino, "cortes_por_tamanho", cortes_tamanho)

    # As medidas da comparação por tamanho, por número de dispositivos e por época.
    # A régua de tokens é a de uma rodada só, para a faixa ser a mesma nos três modelos.
    regua = regua if regua in razao else rodadas[0]
    um = rodadas[0]
    _gravar(destino, "por_tamanho", _por_faixa(por_lei, rodadas, FAIXAS_TOKENS, lambda s: caracteres[s] / razao[regua]))
    _gravar(destino, "por_dispositivos", _por_faixa(por_lei, rodadas, FAIXAS_DISPOSITIVOS,
                                                    lambda s: int(por_lei[s][um]["dispositivos_regex"])))
    _gravar(destino, "por_epoca", _por_faixa(por_lei, rodadas, EPOCAS, lambda s: int(por_lei[s][um]["ano"])))

    # Em quantas leis a árvore é idêntica à do regex, por combinação de rodadas.
    combinacoes = Counter(" + ".join(r for r in rodadas if linhas[r]["identica"] == "1") or "nenhuma"
                          for linhas in por_lei.values())
    _gravar(destino, "concordancia", [{"rodadas_com_arvore_identica": c, "quantas": c.count("+") + 1 if c != "nenhuma" else 0,
                                       "leis": n, "leis_%": round(100 * n / len(por_lei), 1)}
                                      for c, n in combinacoes.most_common()])

    # De que tipo cada dispositivo pende. O regex, em todas as leis comparadas;
    # cada rodada, só nas suas respostas válidas.
    pendura = {"regex": Counter(), **{r: Counter() for r in rodadas}}
    for slug, linhas in por_lei.items():
        ano = linhas[um]["ano"]
        _pendura(json.loads((coleta_ / ano / "json" / f"{slug}.json").read_text(encoding="utf-8")), pendura["regex"])
        for r in rodadas:
            if linhas[r]["valido"] == "1":
                resposta = json.loads((grupo / r / "json" / ano / f"{slug}.json").read_text(encoding="utf-8"))
                _pendura(normalizar(resposta)[0], pendura[r])
    chaves = sorted(set().union(*pendura.values()), key=lambda k: -sum(c[k] for c in pendura.values()))
    _gravar(destino, "pendura", [{"tipo": tipo, "pende_de": pai, **{quem: c[tipo, pai] for quem, c in pendura.items()}}
                                 for tipo, pai in chaves])

    # As leis que ficaram de fora, com a razão resposta/entrada e a velocidade das divididas.
    dispositivos = {a.stem: sum(json.loads(a.read_text(encoding="utf-8")).get("contagem", {}).values())
                    for a in coleta_.glob("*/json/*.json")}
    projecao = []
    for r in rodadas:
        divididas = {s: lei for s, lei in leis[r].items() if lei["dividida"]}
        segundos = tempos.get((r, "divididas"))
        entrada = sum(caracteres[s] for s in longas[r]) / razao[r]
        linha = {"rodada": r, "leis_de_fora": len(longas[r]),
                 "dispositivos_no_regex": sum(dispositivos[s] for s in longas[r]),
                 "dispositivos_%_do_acervo": round(100 * sum(dispositivos[s] for s in longas[r]) / sum(dispositivos.values()), 1),
                 "tokens_de_entrada": round(entrada), "tokens_de_resposta": "", "segundos": "", "unidades": "", "custo_reais": ""}
        if divididas and segundos:
            gerados = sum(lei["tokens"] for lei in divididas.values())
            resposta = entrada * gerados / (sum(caracteres[s] for s in divididas) / razao[r])
            previstos = resposta / (gerados / segundos)
            linha.update({"tokens_de_resposta": round(resposta), "segundos": round(previstos),
                          "unidades": round(previstos / 3600 * UNIDADES_POR_HORA, 1),
                          "custo_reais": round(previstos / 3600 * UNIDADES_POR_HORA * REAIS_POR_UNIDADE, 2)})
        projecao.append(linha)
    _gravar(destino, "projecao", projecao)

    for linha in volume:
        log(f"{linha['rodada']:28s} {linha['leis']:10s} {linha['n_leis']:6d} leis, {linha['pedidos']:6d} pedidos, "
            f"{linha['json_valido']:6d} válidas, {linha['segundos'] or '?':>6} s, R$ {linha['custo_reais'] or '?'}")
    if not tempos:
        log(f"Sem {grupo / 'tempos.csv'}: as colunas de tempo e custo ficaram vazias.")
    log(f"Tabelas em {destino}: volume, cortes, cortes_por_tamanho, por_tamanho, por_dispositivos, por_epoca, "
        "concordancia, pendura, projecao")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelos.analise", description=__doc__.split("\n")[0])
    parser.add_argument("--resultados", default="modelos/resultados/acervo",
                        help="pasta do grupo de rodadas, já comparado por modelos.comparar")
    parser.add_argument("--coleta", default="coleta")
    parser.add_argument("--regua", default="qwen_oficial_restrita",
                        help="rodada cuja razão caracteres/token define as faixas de por_tamanho.csv")
    args = parser.parse_args(argv)
    analisar(args.resultados, args.coleta, args.regua)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
