"""Junta os três ouros revisados (LC 95/1998) num dataset só e o valida.

Lê, a partir da raiz do repositório:
- avaliacao/<anotador>/ouro_<anotador>_lc95.json (Filipe, Paulo e Pedro), a fonte;
- avaliacao/<anotador>/ouro_<anotador>_lc95.xlsx, só para trazer as notas dos revisores;
- avaliacao/amostra/amostra_leis.csv, para a ordem, o estrato e o peso das leis;
- modelos/resultados/lc95/<modelo>_lc95_restrita/json/, para saber quais leis cada modelo respondeu.

Grava em avaliacao/ouro_final/:
- ouro_lc95.json: {slug: {epigrafe, ementa, preambulo, fecho, dispositivos}}, as 376 leis,
  no mesmo formato dos arquivos de cada pasta;
- ouro_lc95.xlsx: abas sobre, leis e dispositivos, gerada do JSON (não editar).

Se alguma validação falhar, nada é gravado.

    python avaliacao/ouro_final/consolidar_ouro.py
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
from collections import Counter
from datetime import date

import openpyxl
import xlsxwriter

RAIZ = pathlib.Path(__file__).resolve().parents[2]
AVALIACAO = RAIZ / "avaliacao"
SAIDA = AVALIACAO / "ouro_final"
LC95 = RAIZ / "modelos" / "resultados" / "lc95"

#: Anotador (pasta) -> quem revisou, na ordem das rodadas de revisão.
REVISORES = {"Filipe": "Paulo", "Paulo": "Pedro", "Pedro": "Filipe (1ª), Paulo (2ª)"}
MODELOS = {"qwen": "qwen_lc95_restrita", "gemma": "gemma12b_lc95_restrita", "llama": "llama_lc95_restrita"}
CAMPOS = ("epigrafe", "ementa", "preambulo", "fecho")
AGRUPADORES = {"parte", "livro", "titulo", "capitulo", "secao", "subsecao", "disposicoes"}
NIVEL = {"artigo": 0, "paragrafo": 1, "inciso": 2, "alinea": 3, "item": 4}
TIPOS = AGRUPADORES | set(NIVEL)


# --- leitura -------------------------------------------------------------------

def amostra() -> list[dict]:
    csv.field_size_limit(10**9)
    with open(AVALIACAO / "amostra" / "amostra_leis.csv", encoding="utf-8-sig", newline="") as f:
        return [{k: l[k] for k in ("slug", "ano", "epoca", "tamanho", "estrato", "peso", "anotador", "origem")}
                for l in csv.DictReader(f)]


def notas(anotador: str) -> dict[str, str]:
    """Nota do revisor por lei, tirada da planilha da pasta (os dois formatos que existem)."""
    ws = openpyxl.load_workbook(AVALIACAO / anotador / f"ouro_{anotador}_lc95.xlsx", read_only=True)["leis"]
    linhas = ws.iter_rows(values_only=True)
    cab = list(next(linhas))
    saida = {}
    for r in linhas:
        l = dict(zip(cab, r))
        if not l.get("slug"):
            continue
        if "alteracoes" in cab:  # planilha gerada do JSON revisado
            texto = "; ".join(x for x in (l.get("nota_do_revisor"), l.get("alteracoes")) if x)
        elif l.get("revisado_por"):  # planilha da extração, marcada pelo revisor
            texto = f"revisada por {str(l['revisado_por']).capitalize()}"
        else:
            texto = ""
        if texto:
            saida[l["slug"]] = texto
    return saida


def respondidas(pasta: str) -> set[str]:
    return {p.stem for p in (LC95 / pasta / "json").rglob("*.json")}


# --- validação -----------------------------------------------------------------

def percorrer(nos: list[dict], pai: str | None = None, caminho: str = ""):
    """Pré-ordem: (nó, tipo do pai, caminho como 'Art. 1º, § 1º, I')."""
    for no in nos:
        cam = rotulo(no) if no["tipo"] in AGRUPADORES or not caminho else f"{caminho}, {rotulo(no)}"
        yield no, pai, cam
        yield from percorrer(no.get("filhos", []), no["tipo"], "" if no["tipo"] in AGRUPADORES else cam)


def rotulo(no: dict) -> str:
    t, n = no["tipo"], no.get("numero") or ""
    varios = bool(re.search(r"\s(a|e)\s|,", n))
    if t == "artigo":
        return f"{'Arts.' if varios else 'Art.'} {n}"
    if t == "paragrafo":
        return "Parágrafo único" if n == "único" else f"{'§§' if varios else '§'} {n}"
    if t == "inciso":
        return n
    if t == "alinea":
        return f"{n})"
    if t == "item":
        return f"{n}."
    if t == "disposicoes":
        return no.get("rubrica") or "DISPOSIÇÕES"
    return f"{t.upper()} {n}".strip()


def validar(ouro: dict, fontes: dict, meta: list[dict]) -> list[str]:
    erros = []
    slugs = [m["slug"] for m in meta]
    if list(ouro) != slugs:
        erros.append(f"leis do ouro ({len(ouro)}) diferentes das da amostra ({len(slugs)})")
    vistos = Counter(s for d in fontes.values() for s in d)
    erros += [f"{s}: em mais de uma pasta" for s, c in vistos.items() if c > 1]
    for m in meta:
        s = m["slug"]
        if s not in fontes[m["anotador"]]:
            erros.append(f"{s}: não está na pasta {m['anotador']}")
        elif ouro.get(s) != fontes[m["anotador"]][s]:
            erros.append(f"{s}: conteúdo diferente do da pasta {m['anotador']}")
    for s, lei in ouro.items():
        if set(lei) != set(CAMPOS) | {"dispositivos"}:
            erros.append(f"{s}: campos {sorted(lei)}")
        erros += [f"{s}: {c} vazio" for c in CAMPOS if not (lei.get(c) or "").strip()]
        num = re.match(r"lei-(\d+)", s).group(1)
        if num not in re.sub(r"\D", "", lei["epigrafe"].split(",")[0]) or s.split("-")[-2] not in lei["epigrafe"]:
            erros.append(f"{s}: epígrafe não bate com o slug")
        if not lei["dispositivos"]:
            erros.append(f"{s}: sem dispositivos")
        irmaos = Counter()
        for no, pai, cam in percorrer(lei["dispositivos"]):
            t = no["tipo"]
            if t not in TIPOS:
                erros.append(f"{s} {cam}: tipo '{t}' desconhecido")
                continue
            if t in NIVEL and not (no.get("texto") or "").strip():
                erros.append(f"{s} {cam}: texto vazio")
            if t in AGRUPADORES and not no.get("rubrica"):
                erros.append(f"{s} {cam}: agrupador sem rubrica")
            if t in NIVEL and pai in NIVEL and NIVEL[t] <= NIVEL[pai]:
                erros.append(f"{s} {cam}: {t} dentro de {pai}")
            if re.search(r"Independ[eê]ncia\s+e\s+\d+", no.get("texto") or "", re.I):
                erros.append(f"{s} {cam}: fecho dentro do dispositivo")
            if "-->" in (no.get("texto") or ""):
                erros.append(f"{s} {cam}: resto de HTML ('-->')")
            if t == "artigo":
                irmaos[(pai, cam)] += 1
        erros += [f"{s} {cam}: artigo repetido" for (_, cam), c in irmaos.items() if c > 1]
        erros += [f"{s}: resto de HTML ('-->') em {c}" for c in CAMPOS if "-->" in lei[c]]
    return erros


# --- gravação ------------------------------------------------------------------

def total(nos: list[dict]) -> int:
    return sum(1 + total(n.get("filhos", [])) for n in nos)


def planilha(ouro: dict, meta: list[dict], nota: dict, modelos: dict[str, set]) -> None:
    leis, disp = [], []
    for m in meta:
        s, lei = m["slug"], ouro[m["slug"]]
        leis.append({
            "slug": s, "ano": int(m["ano"]), "epoca": m["epoca"], "tamanho": m["tamanho"],
            "estrato": m["estrato"], "peso": float(m["peso"]),
            "anotador": m["anotador"], "revisor": REVISORES[m["anotador"]],
            **{c: lei[c] for c in CAMPOS}, "dispositivos": total(lei["dispositivos"]),
            **{f"resposta_{k}": "sim" if s in v else "não" for k, v in modelos.items()},
            "nota_do_revisor": nota.get(s), "origem": m["origem"],
        })
        for i, (no, _, cam) in enumerate(percorrer(lei["dispositivos"]), start=1):
            disp.append({"slug": s, "posicao": i, "tipo": no["tipo"], "numero": no.get("numero"),
                         "caminho": cam, "rubrica": no.get("rubrica"), "texto": no.get("texto") or None})
    por_anotador = Counter(m["anotador"] for m in meta)
    sobre = [
        ("o que é", "Dataset ouro LC 95/1998 consolidado: as 376 leis da amostra, juntando as três pastas revisadas."),
        ("fonte", f"Gerada em {date.today():%d/%m/%Y} por consolidar_ouro.py a partir de ouro_lc95.json. "
                  "O JSON é a fonte: não edite esta planilha; corrija o JSON da pasta do anotador e rode o script de novo."),
        ("origem", "; ".join(f"{a}: {n} leis, revisão de {REVISORES[a]}" for a, n in sorted(por_anotador.items()))),
        ("conteúdo", f"{len(leis)} leis e {len(disp)} dispositivos."),
        ("respostas dos modelos", "; ".join(f"{k}: {len(v & set(ouro))} de {len(ouro)} leis"
                                            for k, v in modelos.items())
                                   + ". Colunas resposta_<modelo> na aba leis."),
        ("aba leis", "Uma linha por lei: época, tamanho, estrato e peso da amostra (N_h / n_h), anotador, revisor, "
                     "os campos da lei, o nº de dispositivos, se cada modelo respondeu e a nota do revisor."),
        ("aba dispositivos", "Uma linha por dispositivo, em pré-ordem (posicao), com tipo, número, "
                             "caminho (ex.: 'Art. 1º, § 1º'), rubrica e texto."),
        ("nomenclatura", "LC 95/1998: epigrafe (art. 4º), ementa (art. 5º), preambulo (art. 6º); agrupadores "
                         "(parte, livro, titulo, capitulo, secao, subsecao, disposicoes) com o nome em 'rubrica' e "
                         "texto vazio; artigo, paragrafo, inciso, alinea, item. O fecho fica em 'fecho', fora do último artigo."),
    ]
    with xlsxwriter.Workbook(SAIDA / "ouro_lc95.xlsx") as wb:
        cab = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1, "valign": "top"})
        quebra = wb.add_format({"text_wrap": True, "valign": "top"})
        topo = wb.add_format({"valign": "top"})

        def aba(nome, linhas, larguras, quebrar=()):
            ws = wb.add_worksheet(nome)
            cols = list(linhas[0])
            ws.write_row(0, 0, cols, cab)
            for i, l in enumerate(linhas, 1):
                for j, c in enumerate(cols):
                    ws.write(i, j, l[c], quebra if c in quebrar else topo)
            for j, c in enumerate(cols):
                ws.set_column(j, j, larguras.get(c, 14))
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, len(linhas), len(cols) - 1)

        aba("sobre", [{"campo": a, "valor": b} for a, b in sobre], {"campo": 20, "valor": 120}, {"valor"})
        aba("leis", leis, {"slug": 38, "estrato": 20, "revisor": 22, "epigrafe": 40, "ementa": 50,
                           "preambulo": 40, "fecho": 50, "nota_do_revisor": 60, "origem": 50},
            {"ementa", "preambulo", "fecho", "nota_do_revisor"})
        aba("dispositivos", disp, {"slug": 38, "caminho": 30, "rubrica": 30, "texto": 90}, {"texto", "rubrica"})
    print(f"ouro_lc95.xlsx: {len(leis)} leis, {len(disp)} dispositivos")


def main() -> int:
    meta = amostra()
    fontes = {a: json.loads((AVALIACAO / a / f"ouro_{a}_lc95.json").read_text(encoding="utf-8"))
              for a in REVISORES}
    ouro = {m["slug"]: fontes[m["anotador"]].get(m["slug"]) for m in meta}
    erros = validar(ouro, fontes, meta)
    if erros:
        print(f"{len(erros)} problema(s); nada foi gravado:", *erros[:50], sep="\n  ")
        return 1
    print(f"validação ok: {len(ouro)} leis, " + ", ".join(f"{a} {len(d)}" for a, d in fontes.items()))
    (SAIDA / "ouro_lc95.json").write_text(json.dumps(ouro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    nota = {s: t for a in REVISORES for s, t in notas(a).items()}
    planilha(ouro, meta, nota, {k: respondidas(p) for k, p in MODELOS.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
