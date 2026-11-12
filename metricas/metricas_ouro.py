"""Compara o dataset ouro com os quatro métodos de fragmentação.

Os métodos são o regex (`coleta/<ano>/json/`) e os três LLMs da rodada j24k
(`modelos/resultados/lc95/<modelo>_lc95_j24k_restrita_junta/`). O ouro é
`avaliacao/ouro_final/ouro_lc95.json`. As 376 leis são as da amostra
(`avaliacao/amostra/amostra_leis.csv`).

As cinco fontes passam pelo mesmo `modelos.resposta.normalizar`, que emenda os
trechos das leis divididas e dá a cada dispositivo um caminho no mesmo padrão
("CAPITULO I, Art. 2º, § 1º, a)").

Métricas por dispositivo do ouro:

- similaridade: Levenshtein normalizada, 1 - distância / maior comprimento,
  entre o texto do ouro e o do método (rubrica + texto, espaços colapsados);
- acerto: 1 se a similaridade for >= LIMIAR (0,95), senão 0.

Os dispositivos são casados pela chave, que é o caminho sem os agrupadores
(ex.: "art. 2º, § 1º, a)"). Os agrupadores (capítulo, seção...) usam o próprio
caminho de agrupadores. Assim, um capítulo que falta não derruba todos os
artigos que ele contém. Chaves repetidas na mesma lei são casadas na ordem.
O dispositivo do ouro que o método não trouxe conta como similaridade 0 e erro.
Esse é o casamento estrito, que cobra o texto e a posição na árvore.

O casamento flexível (colunas `_flex`) faz uma segunda etapa: os dispositivos
do ouro que ficaram sem par recebem, entre as sobras do método, o de texto mais
parecido (similaridade >= MINIMO_TEXTO). Ele mede só o texto. A distância entre
o estrito e o flexível é o custo dos erros de hierarquia e de tipo (ex.: o
modelo pôs "1º" como item e não como inciso, ou o parágrafo como filho do
artigo errado).
O dispositivo que o método trouxe e o ouro não tem ("sobra") também conta como
0 e erro no denominador da lei. A lei sem JSON válido tem todos os dispositivos
como 0.

Métrica global: para cada lei, média da similaridade e taxa de acerto, sobre
(dispositivos do ouro + sobras). Depois, a estimativa estratificada sobre as
15.754 leis da população, sum(W_h * média do estrato), com W_h = N_h / N, e IC
de 95% pela variância da amostragem estratificada. As diferenças entre métodos
usam a mesma conta sobre a diferença lei a lei (pareada), e também os testes de
Friedman e de Wilcoxon pareado com correção de Holm.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
from itertools import combinations

import pandas as pd
from rapidfuzz.distance import Levenshtein
from scipy import stats

from modelos.resposta import normalizar

RAIZ = pathlib.Path(__file__).resolve().parent.parent
OURO = RAIZ / "avaliacao/ouro_final/ouro_lc95.json"
AMOSTRA = RAIZ / "avaliacao/amostra/amostra_leis.csv"
COLETA = RAIZ / "coleta"
LC95 = RAIZ / "modelos/resultados/lc95"

LIMIAR = 0.95
#: No casamento flexível, só casa por texto o par com pelo menos esta similaridade.
MINIMO_TEXTO = 0.5
METODOS = ("regex", "qwen", "gemma", "llama")
PASTAS = {"qwen": "qwen", "gemma": "gemma12b", "llama": "llama"}
METRICAS = ("similaridade", "acuracia", "similaridade_flex", "acuracia_flex")
CAMPOS = ("epigrafe", "ementa", "preambulo", "fecho")
AGRUPADORES = {"parte", "livro", "titulo", "capitulo", "secao", "subsecao", "disposicoes"}
Z = 1.959964


# --- leitura -------------------------------------------------------------------

def ler_amostra() -> pd.DataFrame:
    colunas = ["slug", "ano", "epoca", "tamanho", "estrato", "N_estrato", "n_estrato", "peso", "anotador"]
    return pd.read_csv(AMOSTRA, usecols=colunas)


def ler_ouro() -> dict[str, dict]:
    bruto = json.loads(OURO.read_text(encoding="utf-8"))
    return {slug: normalizar(lei)[0] for slug, lei in bruto.items()}


def ler_regex(slugs) -> dict[str, dict]:
    arquivos = {p.stem: p for p in COLETA.glob("*/json/*.json")}
    return {s: normalizar(json.loads(arquivos[s].read_text(encoding="utf-8")))[0]
            for s in slugs if s in arquivos}


def ler_modelo(metodo: str, slugs) -> dict[str, dict | None]:
    """Resposta normalizada de cada lei, ou None quando não há JSON válido."""
    pasta = LC95 / f"{PASTAS[metodo]}_lc95_j24k_restrita_junta"
    validas = {}
    with (pasta / "registro.csv").open(encoding="utf-8", newline="") as f:
        for linha in csv.reader(f):
            validas[linha[0]] = linha[3] == "1"   # vale a última linha de cada lei
    arquivos = {p.stem: p for p in (pasta / "json").glob("*/*.json")}
    saida = {}
    for s in slugs:
        if validas.get(s) and s in arquivos:
            saida[s] = normalizar(json.loads(arquivos[s].read_text(encoding="utf-8")))[0]
        else:
            saida[s] = None
    return saida


def carregar() -> tuple[pd.DataFrame, dict[str, dict], dict[str, dict]]:
    """Amostra, ouro e {método: {slug: lei normalizada ou None}}."""
    amostra = ler_amostra()
    slugs = list(amostra["slug"])
    ouro = ler_ouro()
    metodos = {"regex": ler_regex(slugs)}
    for m in ("qwen", "gemma", "llama"):
        metodos[m] = ler_modelo(m, slugs)
    return amostra, ouro, metodos


# --- dispositivos --------------------------------------------------------------

def limpar(texto: str | None) -> str:
    return " ".join((texto or "").replace("°", "º").split())


def _chave(caminho: str, tipo: str) -> str:
    partes = [p.strip() for p in caminho.split(",")]
    if tipo not in AGRUPADORES:
        # Tira os agrupadores do começo: a chave começa no artigo.
        for i, p in enumerate(partes):
            if p.lower().startswith("art"):
                partes = partes[i:]
                break
    # O ponto ou parêntese depois do número ("1º.", "a.", "a)") não muda o dispositivo.
    partes = [p.rstrip(".)").strip() for p in partes]
    return limpar(", ".join(partes)).casefold()


def achatar(lei: dict | None) -> list[dict]:
    """Dispositivos em pré-ordem: tipo, caminho, chave, texto."""
    plano: list[dict] = []

    def descer(nos):
        for no in nos:
            plano.append({
                "tipo": no["tipo"],
                "caminho": no.get("caminho") or "",
                "chave": _chave(no.get("caminho") or "", no["tipo"]),
                "texto": limpar(f"{no.get('rubrica') or ''} {no.get('texto') or ''}"),
            })
            descer(no.get("filhos", []))

    if lei:
        descer(lei.get("dispositivos", []))
    return plano


def similaridade(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return Levenshtein.normalized_similarity(a, b)


def casar(do_ouro: list[dict], do_metodo: list[dict]) -> tuple[list[dict | None], list[dict]]:
    """Para cada dispositivo do ouro, o do método de mesma chave (na ordem); e as sobras."""
    filas: dict[str, list[dict]] = {}
    for d in do_metodo:
        filas.setdefault(d["chave"], []).append(d)
    pares = [filas[d["chave"]].pop(0) if filas.get(d["chave"]) else None for d in do_ouro]
    sobras = [d for fila in filas.values() for d in fila]
    return pares, sobras


def casar_por_texto(do_ouro: list[dict], pares: list[dict | None], sobras: list[dict],
                    minimo: float = MINIMO_TEXTO) -> tuple[list[dict | None], list[dict]]:
    """Segunda etapa (casamento flexível): os do ouro que ficaram sem par recebem, das
    sobras, o de texto mais parecido (guloso, do par mais parecido para o menos), se a
    similaridade for >= `minimo`. Mede o texto sem cobrar a posição na árvore."""
    sem_par = [i for i, p in enumerate(pares) if p is None]
    if not sem_par or not sobras:
        return list(pares), list(sobras)
    candidatos = sorted(((similaridade(do_ouro[i]["texto"], s["texto"]), i, j)
                         for i in sem_par for j, s in enumerate(sobras)), reverse=True)
    novos, usados_i, usados_j = list(pares), set(), set()
    for sim, i, j in candidatos:
        if sim < minimo:
            break
        if i in usados_i or j in usados_j:
            continue
        novos[i] = sobras[j]
        usados_i.add(i)
        usados_j.add(j)
    return novos, [s for j, s in enumerate(sobras) if j not in usados_j]


# --- comparação ----------------------------------------------------------------

def comparar(amostra: pd.DataFrame, ouro: dict, metodos: dict) -> dict[str, pd.DataFrame]:
    """Tabelas: dispositivos, sobras, por_lei e campos."""
    info = amostra.set_index("slug")
    disp, sobras, por_lei, campos = [], [], [], []
    for slug in amostra["slug"]:
        base = {"slug": slug, **info.loc[slug, ["ano", "epoca", "tamanho", "estrato", "peso", "anotador"]].to_dict()}
        do_ouro = achatar(ouro[slug])
        linhas = [{**base, "ordem": i + 1, "tipo": d["tipo"], "caminho": d["caminho"],
                   "texto_ouro": d["texto"]} for i, d in enumerate(do_ouro)]
        campo_linha = {**base}
        for m in METODOS:
            lei_m = metodos[m].get(slug)
            pares, sobra = casar(do_ouro, achatar(lei_m))
            pares_flex, sobra_flex = casar_por_texto(do_ouro, pares, sobra)
            sims, sims_flex = [], []
            for linha, d, par, flex in zip(linhas, do_ouro, pares, pares_flex):
                s = similaridade(d["texto"], par["texto"]) if par else 0.0
                sf = similaridade(d["texto"], flex["texto"]) if flex else 0.0
                linha[f"caminho_{m}"] = (par or flex or {}).get("caminho")
                linha[f"texto_{m}"] = (par or flex or {}).get("texto")
                linha[f"sim_{m}"] = round(s, 4)
                linha[f"acerto_{m}"] = int(s >= LIMIAR)
                linha[f"sim_flex_{m}"] = round(sf, 4)
                linha[f"acerto_flex_{m}"] = int(sf >= LIMIAR)
                linha[f"casado_por_{m}"] = "caminho" if par else ("texto" if flex else "faltando")
                sims.append(s)
                sims_flex.append(sf)
            for d in sobra:
                sobras.append({**base, "metodo": m, "tipo": d["tipo"], "caminho": d["caminho"], "texto": d["texto"],
                               "casou_por_texto": "não" if any(d is x for x in sobra_flex) else "sim"})
            denom = len(do_ouro) + len(sobra)
            denom_flex = len(do_ouro) + len(sobra_flex)
            por_lei.append({
                **base, "metodo": m, "json_valido": int(lei_m is not None),
                "dispositivos_ouro": len(do_ouro), "casados": sum(p is not None for p in pares),
                "faltando": sum(p is None for p in pares), "sobrando": len(sobra),
                "similaridade": sum(sims) / denom if denom else 1.0,
                "acuracia": sum(s >= LIMIAR for s in sims) / denom if denom else 1.0,
                "faltando_flex": sum(p is None for p in pares_flex), "sobrando_flex": len(sobra_flex),
                "similaridade_flex": sum(sims_flex) / denom_flex if denom_flex else 1.0,
                "acuracia_flex": sum(s >= LIMIAR for s in sims_flex) / denom_flex if denom_flex else 1.0,
            })
            for c in CAMPOS:
                a, b = limpar(ouro[slug].get(c)), limpar((lei_m or {}).get(c))
                s = similaridade(a, b) if lei_m is not None else 0.0
                campo_linha[f"sim_{c}_{m}"] = round(s, 4)
        campos.append(campo_linha)
        disp.extend(linhas)
    return {"dispositivos": pd.DataFrame(disp), "sobras": pd.DataFrame(sobras),
            "por_lei": pd.DataFrame(por_lei), "campos": pd.DataFrame(campos)}


# --- estatística ---------------------------------------------------------------

def estratificada(df: pd.DataFrame, coluna: str) -> tuple[float, float, float]:
    """Média estratificada e IC de 95%. `df` tem uma linha por lei, com estrato e N_estrato."""
    N = df.groupby("estrato")["N_estrato"].first().sum()
    media, var = 0.0, 0.0
    for _, g in df.groupby("estrato"):
        Nh, nh = g["N_estrato"].iloc[0], len(g)
        Wh = Nh / N
        media += Wh * g[coluna].mean()
        if nh > 1:
            var += Wh ** 2 * (1 - nh / Nh) * g[coluna].var(ddof=1) / nh
    ep = math.sqrt(var)
    return media, media - Z * ep, media + Z * ep


def resumo(tabelas: dict, amostra: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por método: estimativas estratificadas e médias por dispositivo."""
    pl = tabelas["por_lei"].merge(amostra[["slug", "N_estrato"]], on="slug")
    disp = tabelas["dispositivos"]
    linhas = []
    for m in METODOS:
        g = pl[pl["metodo"] == m]
        sim = estratificada(g, "similaridade")
        acc = estratificada(g, "acuracia")
        simf = estratificada(g, "similaridade_flex")
        accf = estratificada(g, "acuracia_flex")
        # Por dispositivo: razão ponderada pelo peso da lei (sobras no denominador).
        peso_den = (g["peso"] * (g["dispositivos_ouro"] + g["sobrando"])).sum()
        linhas.append({
            "metodo": m,
            "leis_json_valido": int(g["json_valido"].sum()),
            "similaridade": sim[0], "sim_ic95_inf": sim[1], "sim_ic95_sup": sim[2],
            "acuracia": acc[0], "acc_ic95_inf": acc[1], "acc_ic95_sup": acc[2],
            "similaridade_flex": simf[0], "simf_ic95_inf": simf[1], "simf_ic95_sup": simf[2],
            "acuracia_flex": accf[0], "accf_ic95_inf": accf[1], "accf_ic95_sup": accf[2],
            "similaridade_por_dispositivo": (disp[f"sim_{m}"] * disp["peso"]).sum() / peso_den,
            "acuracia_por_dispositivo": (disp[f"acerto_{m}"] * disp["peso"]).sum() / peso_den,
            "dispositivos_ouro": int(g["dispositivos_ouro"].sum()),
            "faltando": int(g["faltando"].sum()), "sobrando": int(g["sobrando"].sum()),
            "acertos": int(disp[f"acerto_{m}"].sum()),
            "faltando_flex": int(g["faltando_flex"].sum()), "sobrando_flex": int(g["sobrando_flex"].sum()),
            "acertos_flex": int(disp[f"acerto_flex_{m}"].sum()),
        })
    r = pd.DataFrame(linhas).sort_values("similaridade", ascending=False)
    r.insert(1, "posicao", range(1, len(r) + 1))
    return r


def _holm(pvalores: list[float]) -> list[float]:
    ordem = sorted(range(len(pvalores)), key=lambda i: pvalores[i])
    ajust, maximo = [0.0] * len(pvalores), 0.0
    for k, i in enumerate(ordem):
        maximo = max(maximo, min(1.0, (len(pvalores) - k) * pvalores[i]))
        ajust[i] = maximo
    return ajust


def testes(tabelas: dict, amostra: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Friedman por métrica e, para cada par, diferença estratificada com IC e Wilcoxon-Holm."""
    pl = tabelas["por_lei"]
    friedman, pares = [], []
    for metrica in METRICAS:
        larga = pl.pivot(index="slug", columns="metodo", values=metrica)[list(METODOS)]
        est, p = stats.friedmanchisquare(*[larga[m] for m in METODOS])
        friedman.append({"metrica": metrica, "qui_quadrado": est, "p_valor": p, "leis": len(larga)})
        bloco = []
        for a, b in combinations(METODOS, 2):
            dif = (larga[a] - larga[b]).rename("dif").reset_index().merge(
                amostra[["slug", "estrato", "N_estrato"]], on="slug")
            media, inf, sup = estratificada(dif, "dif")
            try:
                w = stats.wilcoxon(larga[a], larga[b], zero_method="wilcox")
                pw = w.pvalue
            except ValueError:   # todas as diferenças iguais a zero
                pw = 1.0
            bloco.append({"metrica": metrica, "metodo_a": a, "metodo_b": b,
                          "diferenca_a_menos_b": media, "dif_ic95_inf": inf, "dif_ic95_sup": sup,
                          "a_melhor_em": int((larga[a] > larga[b]).sum()),
                          "b_melhor_em": int((larga[a] < larga[b]).sum()),
                          "empates": int((larga[a] == larga[b]).sum()),
                          "wilcoxon_p": pw})
        for linha, pa in zip(bloco, _holm([x["wilcoxon_p"] for x in bloco])):
            linha["wilcoxon_p_holm"] = pa
            linha["significativo_5pct"] = "sim" if pa < 0.05 else "não"
        pares.extend(bloco)
    return pd.DataFrame(friedman), pd.DataFrame(pares)


def por_grupo(tabelas: dict, amostra: pd.DataFrame, grupo: str) -> pd.DataFrame:
    """Médias por época, tamanho ou estrato (estratificadas dentro do grupo)."""
    pl = tabelas["por_lei"].merge(amostra[["slug", "N_estrato"]], on="slug")
    linhas = []
    for (valor, m), g in pl.groupby([grupo, "metodo"]):
        linhas.append({grupo: valor, "metodo": m, "leis": len(g),
                       **{c: estratificada(g, c)[0] for c in METRICAS}})
    t = pd.DataFrame(linhas)
    return t.pivot(index=grupo, columns="metodo", values=list(METRICAS))[
        [(c, m) for c in METRICAS for m in METODOS]]


def por_tipo(tabelas: dict) -> pd.DataFrame:
    """Por tipo de dispositivo do ouro (sem sobras e sem peso): quantos, similaridade e acurácia."""
    disp = tabelas["dispositivos"]
    linhas = []
    for tipo, g in disp.groupby("tipo"):
        linha = {"tipo": tipo, "dispositivos": len(g)}
        for m in METODOS:
            linha[f"sim_{m}"] = g[f"sim_{m}"].mean()
            linha[f"acc_{m}"] = g[f"acerto_{m}"].mean()
            linha[f"sim_flex_{m}"] = g[f"sim_flex_{m}"].mean()
            linha[f"acc_flex_{m}"] = g[f"acerto_flex_{m}"].mean()
            linha[f"faltando_{m}"] = int((g[f"casado_por_{m}"] != "caminho").sum())
            linha[f"faltando_flex_{m}"] = int((g[f"casado_por_{m}"] == "faltando").sum())
        linhas.append(linha)
    return pd.DataFrame(linhas).sort_values("dispositivos", ascending=False)


def resumo_campos(tabelas: dict) -> pd.DataFrame:
    c = tabelas["campos"]
    return pd.DataFrame([{"campo": campo, **{m: c[f"sim_{campo}_{m}"].mean() for m in METODOS},
                          **{f"acc_{m}": (c[f"sim_{campo}_{m}"] >= LIMIAR).mean() for m in METODOS}}
                         for campo in CAMPOS])


# --- Excel ---------------------------------------------------------------------

SOBRE = [
    ("O que é", "Comparação do dataset ouro (376 leis) com o regex e os três LLMs (rodada j24k, pasta _junta)."),
    ("Similaridade", "Levenshtein normalizada: 1 - distância de edição / maior comprimento. 1 = texto idêntico."),
    ("Acerto", f"1 quando a similaridade é >= {LIMIAR}. Acurácia = fração de acertos."),
    ("Casamento", "Pelo caminho sem os agrupadores (ex.: 'Art. 2º, § 1º, a)'); agrupadores pelo próprio caminho. "
                  "Repetidos na mesma lei, na ordem."),
    ("Casamento flexível (_flex)", f"Depois do caminho, os do ouro sem par recebem a sobra de texto mais parecido "
                                   f"(guloso, similaridade >= {MINIMO_TEXTO}). Mede o texto sem cobrar a posição "
                                   "na árvore; a diferença para a estrita é o custo dos erros de hierarquia/tipo."),
    ("Faltando", "Dispositivo do ouro sem par no método: similaridade 0 e erro."),
    ("Sobrando", "Dispositivo do método sem par no ouro: entra como 0 e erro no denominador da lei (aba sobras)."),
    ("Lei sem JSON", "Todos os dispositivos da lei contam como 0 e erro."),
    ("Global (lei)", "Média por lei; depois estimativa estratificada sum(W_h * média_h), W_h = N_h/N, "
                     "com IC 95% da amostragem estratificada (com correção de população finita)."),
    ("Global (dispositivo)", "Soma das similaridades (ou acertos) / dispositivos, ponderando cada um pelo peso da lei."),
    ("Testes", "Friedman entre os 4 métodos e Wilcoxon pareado por lei com correção de Holm (sem pesos)."),
    ("Texto", "Rubrica + texto, espaços colapsados, ° trocado por º. Maiúsculas e acentos contam."),
    ("Fontes", "avaliacao/ouro_final/ouro_lc95.json; coleta/<ano>/json; "
               "modelos/resultados/lc95/<modelo>_lc95_j24k_restrita_junta."),
]


def gravar_excel(caminho: pathlib.Path, abas: dict[str, pd.DataFrame]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(caminho, engine="xlsxwriter") as w:
        livro = w.book
        quebra = livro.add_format({"text_wrap": True, "valign": "top"})
        pct = livro.add_format({"num_format": "0.0000"})
        for nome, df in abas.items():
            df = df.copy()
            for c in df.columns:
                if df[c].dtype == object:
                    df[c] = df[c].map(lambda v: v[:32000] if isinstance(v, str) else v)
            indice = isinstance(df.columns, pd.MultiIndex)
            df.to_excel(w, sheet_name=nome, index=indice)
            folha = w.sheets[nome]
            if not indice:
                folha.freeze_panes(1, 0)
                folha.autofilter(0, 0, len(df), len(df.columns) - 1)
            for i, c in enumerate(df.columns):
                nome_c = c if isinstance(c, str) else " ".join(map(str, c))
                if nome_c.startswith("texto") or nome_c in ("Descrição",):
                    folha.set_column(i, i, 60, quebra)
                elif df[c].dtype.kind == "f":
                    folha.set_column(i + int(indice), i + int(indice), 12, pct)
                elif nome_c in ("slug",):
                    folha.set_column(i, i, 36)
                elif nome_c in ("caminho",):
                    folha.set_column(i, i, 28)


def exportar(tabelas: dict, amostra: pd.DataFrame, pasta: pathlib.Path) -> pathlib.Path:
    """Grava a planilha com todas as abas e os CSVs do resumo e por lei."""
    friedman, pares = testes(tabelas, amostra)
    base = ["slug", "ano", "epoca", "tamanho", "estrato", "peso", "anotador", "ordem", "tipo", "caminho", "texto_ouro"]
    por_metodo = [f"{c}_{m}" for m in METODOS
                  for c in ("caminho", "texto", "casado_por", "sim", "acerto", "sim_flex", "acerto_flex")]
    disp = tabelas["dispositivos"][base + por_metodo]
    r = resumo(tabelas, amostra)
    abas = {
        "sobre": pd.DataFrame(SOBRE, columns=["Item", "Descrição"]),
        "resumo": r,
        "friedman": friedman,
        "pares": pares,
        "por_epoca": por_grupo(tabelas, amostra, "epoca"),
        "por_tamanho": por_grupo(tabelas, amostra, "tamanho"),
        "por_estrato": por_grupo(tabelas, amostra, "estrato"),
        "por_tipo": por_tipo(tabelas),
        "campos_resumo": resumo_campos(tabelas),
        "por_lei": tabelas["por_lei"],
        "dispositivos": disp,
        "sobras": tabelas["sobras"],
        "campos": tabelas["campos"],
    }
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "comparacao_ouro.xlsx"
    gravar_excel(arquivo, abas)
    r.to_csv(pasta / "resumo.csv", index=False, encoding="utf-8")
    pares.to_csv(pasta / "pares.csv", index=False, encoding="utf-8")
    tabelas["por_lei"].to_csv(pasta / "por_lei.csv", index=False, encoding="utf-8")
    return arquivo


def main() -> int:
    amostra, ouro, metodos = carregar()
    tabelas = comparar(amostra, ouro, metodos)
    arquivo = exportar(tabelas, amostra, RAIZ / "metricas/resultados")
    print(resumo(tabelas, amostra).round(4).to_string(index=False))
    print(f"\nGravado: {arquivo.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
