"""Amostra de Cochran (5% de erro, 95% de confiança) e o dataset unificado da amostra.

Roda a partir da raiz do repositório extrator_fragmentos_leis (usa o código dele
para ler e normalizar as respostas dos modelos). Grava em SAIDA:
- amostra_leis.csv: uma linha por lei, com a lei bruta e o JSON de cada método;
- dispositivos_longo.csv: uma linha por dispositivo, alinhado entre os métodos pelo
  caminho, com o texto que cada método deu;
- ouro_rascunho.csv: a árvore do regex aberta em linhas, para os anotadores
  corrigirem contra a lei e chegarem ao ouro;
- ../<anotador>/: uma pasta por anotador, com anotacao_<anotador>.xlsx e o HTML das
  leis dele em leis/.
"""
import json, math, pathlib, random, sys

import pandas as pd

REPO = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SAIDA = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "amostra").resolve()
sys.path.insert(0, str(REPO))

from modelos.comparar import achatar, ler_rodada, _ler_resposta
from modelos.entrada import preparar

COLETA = REPO / "coleta"
ACERVO = REPO / "modelos" / "resultados" / "acervo"
METODOS = {"qwen": "qwen_oficial_restrita", "gemma": "gemma12b_oficial_restrita",
           "llama": "llama_oficial_restrita"}
ANOTADORES = ["Paulo", "Pedro", "Filipe"]
ERRO, Z, P = 0.05, 1.96, 0.5
SEMENTE = 2026


# --- população: leis que os três modelos responderam --------------------------
rodadas = {m: ler_rodada(ACERVO / pasta) for m, pasta in METODOS.items()}
populacao = sorted(set.intersection(*(set(r) for r in rodadas.values())))
N = len(populacao)

n0 = Z**2 * P * (1 - P) / ERRO**2
n = math.ceil(n0 / (1 + (n0 - 1) / N))
print(f"População: {N} leis. Cochran: n0 = {n0:.1f}, com correção finita n = {n}.")

# --- estratos: época x tamanho, alocação proporcional --------------------------
def regex_de(slug):
    ano = rodadas["qwen"][slug]["ano"]
    return json.loads((COLETA / ano / "json" / f"{slug}.json").read_text(encoding="utf-8"))

pop = pd.DataFrame({"slug": populacao, "ano": [int(rodadas["qwen"][s]["ano"]) for s in populacao]})
pop["dispositivos_regex"] = [sum(regex_de(s)["contagem"].values()) for s in pop["slug"]]
pop["epoca"] = pd.cut(pop["ano"], [0, 1945, 1988, 9999], labels=["1891-1945", "1946-1988", "1989-2026"])
pop["tamanho"] = pd.qcut(pop["dispositivos_regex"].rank(method="first"), 3, labels=["pequena", "media", "grande"])
pop["estrato"] = pop["epoca"].astype(str) + " | " + pop["tamanho"].astype(str)

tamanhos = pop["estrato"].value_counts().sort_index()
cota = tamanhos * n / N
alocacao = cota.astype(int)
for estrato in (cota - alocacao).sort_values(ascending=False).index[: n - alocacao.sum()]:
    alocacao[estrato] += 1   # maiores restos

rng = random.Random(SEMENTE)
partes = []
for estrato, k in alocacao.items():
    slugs = sorted(pop.loc[pop["estrato"] == estrato, "slug"])
    partes.append(pop[pop["slug"].isin(rng.sample(slugs, k))])
amostra = pd.concat(partes).sort_values(["estrato", "slug"]).reset_index(drop=True)
amostra["N_estrato"] = amostra["estrato"].map(tamanhos)
amostra["n_estrato"] = amostra["estrato"].map(alocacao)
amostra["peso"] = amostra["N_estrato"] / amostra["n_estrato"]

# --- anotadores: rodízio dentro de cada estrato; cada lei com um só anotador ---
ordem = amostra.sample(frac=1, random_state=SEMENTE).sort_values("estrato", kind="stable").index
amostra.loc[ordem, "anotador"] = [ANOTADORES[i % 3] for i in range(len(ordem))]

# --- dataset unificado ---------------------------------------------------------
linhas_lei, linhas_disp, linhas_ouro = [], [], []
for _, lei in amostra.iterrows():
    slug, ano = lei["slug"], str(lei["ano"])
    html_pagina = (COLETA / ano / "html" / f"{slug}.html").read_text(encoding="utf-8")
    regex = regex_de(slug)
    arvores = {"regex": regex}
    linha = {**lei.to_dict(), "origem": regex.get("origem"), "titulo": regex.get("titulo"),
             "lei_html": preparar(html_pagina, "html"), "lei_texto": preparar(html_pagina, "texto")}
    for metodo, pasta in METODOS.items():
        info = rodadas[metodo][slug]
        normal, reparada, _ = _ler_resposta(ACERVO / pasta, slug, info, regex)
        arvores[metodo] = normal
        linha[f"estado_{metodo}"] = ("valido" if normal is not None
                                    else "reparado" if reparada is not None else "invalido")
        linha[f"cortada_{metodo}"] = int(info["cortada"])
    for metodo, arvore in arvores.items():
        linha[f"json_{metodo}"] = json.dumps(arvore, ensure_ascii=False) if arvore else ""
        linha[f"dispositivos_{metodo}"] = len(achatar(arvore)) if arvore else 0
    linhas_lei.append(linha)

    # Alinha os dispositivos pelo caminho; o mesmo caminho repetido casa pela ocorrência.
    chaves, por_metodo = [], {}
    for metodo, arvore in arvores.items():
        vistos, ultimo, itens = {}, -1, {}
        for d in achatar(arvore) if arvore else []:
            k = (d["caminho"], vistos.get(d["caminho"], 0))
            vistos[d["caminho"]] = k[1] + 1
            itens[k] = d
            if k in chaves:
                ultimo = chaves.index(k)
            else:
                ultimo += 1
                chaves.insert(ultimo, k)
        por_metodo[metodo] = itens
    # Rascunho do ouro: a árvore do regex, um dispositivo por linha, para corrigir.
    def abrir(nos):
        for no in nos:
            yield no
            yield from abrir(no.get("filhos", []))
    for posicao, no in enumerate(abrir(regex.get("dispositivos", [])), 1):
        linhas_ouro.append({
            "slug": slug, "anotador": lei["anotador"],
            "posicao": posicao, "acao": "", "tipo": no["tipo"], "numero": no.get("numero") or "",
            "caminho": no.get("caminho") or "", "rubrica": no.get("rubrica") or "",
            "texto": no.get("texto") or "", "observacao": ""})

    for posicao, k in enumerate(chaves, 1):
        achados = {m: por_metodo[m].get(k) for m in arvores}
        tipo = next(d["tipo"] for d in achados.values() if d)
        linhas_disp.append({
            "slug": slug, "anotador": lei["anotador"],
            "estrato": lei["estrato"], "posicao": posicao, "caminho": k[0], "tipo": tipo,
            **{f"em_{m}": int(d is not None) for m, d in achados.items()},
            "n_metodos": sum(d is not None for d in achados.values()),
            **{f"texto_{m}": d["texto"] if d else "" for m, d in achados.items()},
        })

SAIDA.mkdir(parents=True, exist_ok=True)
leis = pd.DataFrame(linhas_lei)
dispositivos = pd.DataFrame(linhas_disp)
leis.to_csv(SAIDA / "amostra_leis.csv", index=False, encoding="utf-8-sig")
dispositivos.to_csv(SAIDA / "dispositivos_longo.csv", index=False, encoding="utf-8-sig")
ouro = pd.DataFrame(linhas_ouro)
ouro.to_csv(SAIDA / "ouro_rascunho.csv", index=False, encoding="utf-8-sig")

# Uma pasta por anotador: a planilha de anotação e a página HTML de cada lei dele.
for anotador in ANOTADORES:
    pasta = SAIDA.parent / anotador
    (pasta / "leis").mkdir(parents=True, exist_ok=True)
    minhas = leis[leis["anotador"] == anotador]
    with pd.ExcelWriter(pasta / f"anotacao_{anotador}.xlsx") as planilha:
        minhas[["slug", "ano", "titulo", "origem", "estrato"]].assign(
            arquivo=lambda t: "leis/" + t["slug"] + ".html").to_excel(planilha, sheet_name="leis", index=False)
        ouro[ouro["slug"].isin(minhas["slug"])].drop(columns=["anotador"]).to_excel(
            planilha, sheet_name="ouro", index=False)
    for _, lei in minhas.iterrows():
        origem = COLETA / str(lei["ano"]) / "html" / f"{lei['slug']}.html"
        (pasta / "leis" / origem.name).write_bytes(origem.read_bytes())

print(f"{len(ouro)} dispositivos no rascunho do ouro.")
print(f"{len(leis)} leis e {len(dispositivos)} linhas de dispositivos gravadas em {SAIDA}.")
print(alocacao.to_string())
print(leis.groupby("anotador").agg(leis=("slug", "size"), dispositivos=("dispositivos_regex", "sum")).to_string())
print(pd.crosstab(leis["estrato"], leis["anotador"]).to_string())
