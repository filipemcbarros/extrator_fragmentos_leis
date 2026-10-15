"""Piloto: 5 leis da amostra, um mini-ouro feito à mão e a comparação dos 4 métodos.

O mini-ouro foi montado lendo o texto de cada lei: a estrutura (quais dispositivos
existem e de quem cada um pende) foi decidida na leitura, e o texto de cada
dispositivo é copiado da própria lei, sem o rótulo. Convenção: o texto citado de
outra lei (redação nova entre aspas) faz parte do artigo que o cita e não vira
dispositivo desta lei.

Medidas, sempre contra o ouro, casando os dispositivos pelo caminho completo
("Art. 3º, I"):
- similaridade: 1 - distância de Levenshtein normalizada entre o texto do ouro e o
  do método; dispositivo não encontrado vale 0;
- % >= 0,9: dispositivos do ouro achados no lugar certo com texto quase igual;
- não encontrados: dispositivos do ouro que o método não pôs no lugar certo;
- precisão, revocação e F1 estritos: acerto = mesmo caminho e similaridade >= 0,9;
  os dispositivos que o método inventou ou pendurou errado derrubam a precisão.

    python piloto_5_leis.py <raiz do repositório> <pasta de saída>
"""
import json, pathlib, re, sys

import pandas as pd
from rapidfuzz.distance import Levenshtein

REPO = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SAIDA = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "piloto").resolve()
sys.path.insert(0, str(REPO))
from modelos.comparar import achatar, ler_rodada, _ler_resposta, _chave
from modelos.entrada import preparar

COLETA = REPO / "coleta"
ACERVO = REPO / "modelos" / "resultados" / "acervo"
MODELOS = {"qwen": "qwen_oficial_restrita", "gemma": "gemma12b_oficial_restrita",
           "llama": "llama_oficial_restrita"}
METODOS = ["regex", *MODELOS]
LIMIAR = 0.9

# --- mini-ouro: (caminho, início da linha na lei) ------------------------------
def artigos(n, extra=None):
    """Artigos 1..n, cada um começando na linha "Art. Nº" (ou "Art Nº")."""
    return [(f"Art. {i}º" if i < 10 else f"Art. {i}", rf"Art\.? {i}º?\b") for i in range(1, n + 1)]

OURO = {
    "lei-448-6-outubro-1897-539512": [
        ("Art. 1º", r"Art\. 1º"), ("Art. 1º, § 1º", r"§ 1º"), ("Art. 1º, § 2º", r"§ 2º"),
        ("Art. 1º, § 3º", r"§ 3º"), ("Art. 2º", r"Art\. 2º"), ("Art. 3º", r"Art\. 3º"),
        ("Art. 4º", r"Art\. 4º"), ("Art. 5º", r"Art\. 5º"),
        ("Art. 5º, Parágrafo único", r"Paragrapho unico"),
        ("Art. 6º", r"Art\. 6º"), ("Art. 7º", r"Art\. 7º")],
    "lei-1220-28-outubro-1950-363531": artigos(8),
    "lei-6225-14-julho-1975-357701": [
        ("Art. 1º", r"Art\. 1º"), ("Art. 1º, Parágrafo único", r"Parágrafo único"),
        ("Art. 2º", r"Art\. 2º"), ("Art. 2º, Parágrafo único", r"Parágrafo único"),
        ("Art. 3º", r"Art\. 3º"), ("Art. 3º, § 1º", r"§ 1º"), ("Art. 3º, § 2º", r"§ 2º"),
        ("Art. 3º, § 3º", r"§ 3º"), ("Art. 4º", r"Art\. 4º"),
        ("Art. 4º, Parágrafo único", r"Parágrafo único"),
        ("Art. 5º", r"Art\. 5º"), ("Art. 6º", r"Art\. 6º"), ("Art. 7º", r"Art\. 7º")],
    "lei-7431-17-dezembro-1985-368048": [
        ("Art. 1º", r"Art 1º"), *[(f"Art. 1º, § {i}º", rf"§ {i}º") for i in range(1, 5)],
        ("Art. 2º", r"Art 2º"), *[(f"Art. 2º, § {i}º", rf"§ {i}º") for i in range(1, 5)],
        ("Art. 3º", r"Art 3º"), *[(f"Art. 3º, {r}", rf"{r} -") for r in ("I", "II", "III")],
        ("Art. 4º", r"Art\. 4º"), *[(f"Art. 4º, {r}", rf"{r} -") for r in ("I", "II", "III", "IV")],
        ("Art. 4º, Parágrafo único", r"Parágrafo único"),
        ("Art. 5º", r"Art 5º"), ("Art. 5º, Parágrafo único", r"Parágrafo único"),
        ("Art. 6º", r"Art 6º"), ("Art. 6º, Parágrafo único", r"Parágrafo único"),
        ("Art. 7º", r"Art 7º"), ("Art. 7º, Parágrafo único", r"Parágrafo único"),
        ("Art. 8º", r"Art 8º"), ("Art. 9º", r"Art 9º"), ("Art. 10", r"Art\. 10")],
    "lei-8044-15-junho-1990-365703": [
        ("Art. 1º", r"Art\. 1º"), ("Art. 1º, I", r"I -"), ("Art. 1º, II", r"II -"),
        ("Art. 1º, Parágrafo único", r"Parágrafo único"),
        ("Art. 2º", r"Art\. 2º"), ("Art. 3º", r"Art\. 3º"), ("Art. 4º", r"Art\. 4º"),
        ("Art. 5º", r"Art\. 5º")],
}

ROTULO = re.compile(r"^(?:Art\.?\s*\d+º?\.?|§\s*\d+º|Par[áa]grapho unico\.?|Parágrafo único\.?|[IVXL]+)\s*[-–]?\s*")
FIM = re.compile(r"^(Capital Federal|Rio de Janeiro|Brasília),")


def montar_ouro(slug, linhas):
    """Texto de cada dispositivo do ouro: da sua linha até a linha anterior ao próximo."""
    inicios, i = [], 0
    for caminho, marca in OURO[slug]:
        while not re.match(marca, linhas[i]):
            i += 1
        inicios.append(i)
        i += 1
    fim = next(j for j in range(inicios[-1], len(linhas)) if FIM.match(linhas[j]))
    ouro = []
    for k, (caminho, _) in enumerate(OURO[slug]):
        bloco = linhas[inicios[k]: inicios[k + 1] if k + 1 < len(inicios) else fim]
        texto = " ".join(" ".join(bloco).split())
        ouro.append({"caminho": caminho, "tipo": tipo_de(caminho),
                     "texto": ROTULO.sub("", texto, count=1)})
    return ouro


def tipo_de(caminho):
    ultimo = caminho.split(", ")[-1]
    return ("artigo" if ultimo.startswith("Art") else "paragrafo" if ultimo.startswith(("§", "Par"))
            else "inciso")


def com_ocorrencia(dispositivos, campo="caminho"):
    """Chave (caminho normalizado, ocorrência) -> dispositivo."""
    vistos, saida = {}, {}
    for d in dispositivos:
        c = _chave(d[campo])
        saida[(c, vistos.get(c, 0))] = d
        vistos[c] = vistos.get(c, 0) + 1
    return saida


def semelhanca(a, b):
    return Levenshtein.normalized_similarity(" ".join(a.split()), " ".join(b.split()))


lado, por_lei, ouro_tabela = [], [], []
rodadas = {m: ler_rodada(ACERVO / p) for m, p in MODELOS.items()}
for slug in OURO:
    ano = rodadas["qwen"][slug]["ano"]
    pagina = (COLETA / ano / "html" / f"{slug}.html").read_text(encoding="utf-8")
    linhas = preparar(pagina, "texto").splitlines()
    ouro = montar_ouro(slug, linhas)
    ouro_tabela += [{"slug": slug, **d} for d in ouro]

    regex = json.loads((COLETA / ano / "json" / f"{slug}.json").read_text(encoding="utf-8"))
    arvores = {"regex": regex}
    for m, pasta in MODELOS.items():
        arvores[m] = _ler_resposta(ACERVO / pasta, slug, rodadas[m][slug], regex)[0]
    planos = {m: com_ocorrencia(achatar(a)) if a else {} for m, a in arvores.items()}
    chaves_ouro = com_ocorrencia(ouro)

    # Lado a lado: os dispositivos do ouro, depois os que só os métodos têm.
    for chave, d in chaves_ouro.items():
        linha = {"slug": slug, "caminho": d["caminho"], "no_ouro": 1, "texto_ouro": d["texto"]}
        for m in METODOS:
            achado = planos[m].get(chave)
            linha[f"texto_{m}"] = achado["texto"] if achado else ""
            linha[f"sim_{m}"] = round(semelhanca(d["texto"], achado["texto"]), 3) if achado else 0.0
        lado.append(linha)
    extras = {}
    for m in METODOS:
        for chave, d in planos[m].items():
            if chave not in chaves_ouro:
                extras.setdefault(chave, {"slug": slug, "caminho": d["caminho"], "no_ouro": 0, "texto_ouro": ""})
                extras[chave][f"texto_{m}"] = d["texto"]
    for linha in extras.values():
        for m in METODOS:
            linha.setdefault(f"texto_{m}", "")
            linha[f"sim_{m}"] = None
        lado.append(linha)

    for m in METODOS:
        sims = [semelhanca(d["texto"], planos[m][k]["texto"]) if k in planos[m] else 0.0
                for k, d in chaves_ouro.items()]
        certos = sum(s >= LIMIAR for s in sims)
        p = certos / len(planos[m]) if planos[m] else 0.0
        r = certos / len(sims)
        por_lei.append({
            "slug": slug, "metodo": m, "dispositivos_ouro": len(sims), "dispositivos_metodo": len(planos[m]),
            "similaridade_media": round(sum(sims) / len(sims), 3),
            "pct_sim_ge_0.9": round(100 * certos / len(sims), 1),
            "pct_nao_encontrados": round(100 * sum(k not in planos[m] for k in chaves_ouro) / len(sims), 1),
            "inventados_ou_fora_do_lugar": sum(k not in chaves_ouro for k in planos[m]),
            "precisao": round(p, 3), "revocacao": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
        })

por_lei = pd.DataFrame(por_lei)
resumo = (por_lei.groupby("metodo", sort=False)
          [["similaridade_media", "pct_sim_ge_0.9", "pct_nao_encontrados", "precisao", "revocacao", "f1"]]
          .mean().round(3).sort_values("f1", ascending=False))
f1_lado = por_lei.pivot(index="slug", columns="metodo", values="f1")[METODOS]
sim_lado = por_lei.pivot(index="slug", columns="metodo", values="similaridade_media")[METODOS]

SAIDA.mkdir(parents=True, exist_ok=True)
with pd.ExcelWriter(SAIDA / "piloto_5_leis.xlsx") as x:
    resumo.to_excel(x, sheet_name="resumo")
    f1_lado.to_excel(x, sheet_name="f1_por_lei")
    sim_lado.to_excel(x, sheet_name="similaridade_por_lei")
    por_lei.to_excel(x, sheet_name="por_lei", index=False)
    pd.DataFrame(lado).to_excel(x, sheet_name="lado_a_lado", index=False)
    pd.DataFrame(ouro_tabela).to_excel(x, sheet_name="mini_ouro", index=False)
pd.DataFrame(lado).to_csv(SAIDA / "piloto_lado_a_lado.csv", index=False, encoding="utf-8-sig")
por_lei.to_csv(SAIDA / "piloto_por_lei.csv", index=False, encoding="utf-8-sig")
print(resumo.to_string(), "\n")
print("F1 por lei:\n", f1_lado.to_string(), "\n")
print("Similaridade média por lei:\n", sim_lado.to_string())
