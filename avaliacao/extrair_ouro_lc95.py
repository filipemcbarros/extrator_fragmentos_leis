"""Nova extração do ouro com o extrator ajustado à LC 95/1998.

Fragmenta de novo as 376 leis da amostra, cada uma a partir do HTML que já está
na pasta do revisor (avaliacao/<revisor>/leis/), e mantém a divisão anterior:
125 Filipe, 125 Pedro, 126 Paulo. Para cada revisor grava:

- ouro_<revisor>_lc95.json: {slug: {epigrafe, ementa, preambulo, fecho, dispositivos}},
  no formato do ouro anterior, com "epigrafe" no lugar de "titulo";
- ouro_<revisor>_lc95.xlsx: abas sobre, leis e ouro, como a planilha anterior.

Os arquivos revisados (ouro_<revisor>.json, paulo_ouro_v3.json) não são tocados.
Cada lei e cada dispositivo é comparado com o ouro revisado, para o revisor ver
onde a nova extração diverge do que já foi conferido.

Roda a partir da raiz do repositório:  python avaliacao/extrair_ouro_lc95.py
Depende só de xlsxwriter, além do próprio fragmentador.
"""
import csv
import json
import pathlib
import re
import sys
from collections import Counter
from datetime import date

import xlsxwriter

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fragmentador import fragmentar_referencia  # noqa: E402
from fragmentador.modelos import campo_da_lei  # noqa: E402

AVALIACAO = REPO / "avaliacao"
AMOSTRA = AVALIACAO / "amostra" / "amostra_leis.csv"
REVISORES = {"Filipe": 125, "Pedro": 125, "Paulo": 126}
#: Ouro já revisado de cada um (o do Paulo é a terceira versão).
OURO_REVISADO = {"Filipe": "ouro_Filipe.json", "Pedro": "ouro_Pedro.json",
                 "Paulo": "paulo_ouro_v3.json"}
CAMPOS = ("epigrafe", "ementa", "preambulo", "fecho")
STATUS = "pendente de revisão humana"


# --- formato do ouro ---------------------------------------------------------

def dispositivo(d: dict) -> dict:
    """Converte a saída do fragmentador para o formato do ouro (sem rotulo/caminho/linha)."""
    saida = {"tipo": d["tipo"], "numero": d["numero"]}
    if d.get("rubrica"):
        saida["rubrica"] = d["rubrica"]
    saida["texto"] = d["texto"]
    if d.get("filhos"):
        saida["filhos"] = [dispositivo(f) for f in d["filhos"]]
    return saida


def normal(texto: str | None) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def chaves(dispositivos: list[dict], pais: tuple = ()) -> Counter:
    """Cada dispositivo vira (ancestrais, tipo, número, rubrica, texto) para comparar árvores."""
    c: Counter = Counter()
    for d in dispositivos:
        k = (pais, d["tipo"], normal(d.get("numero")), normal(d.get("rubrica")), normal(d.get("texto")))
        c[k] += 1
        c += chaves(d.get("filhos", []), pais + ((d["tipo"], normal(d.get("numero"))),))
    return c


def total(dispositivos: list[dict]) -> int:
    return sum(1 + total(d.get("filhos", [])) for d in dispositivos)


def diferencas(novo: dict, antigo: dict | None) -> str:
    if antigo is None:
        return "lei ausente do ouro revisado"
    partes = [f"{c} difere" for c in CAMPOS if normal(novo[c]) != normal(campo_da_lei(antigo, c))]
    a, b = chaves(novo["dispositivos"]), chaves(antigo.get("dispositivos", []))
    so_novo, so_antigo = sum((a - b).values()), sum((b - a).values())
    if so_novo or so_antigo:
        partes.append(f"{so_novo} dispositivo(s) só na nova extração, {so_antigo} só no ouro revisado")
    return "; ".join(partes)


# --- extração ----------------------------------------------------------------

def amostra() -> list[dict]:
    csv.field_size_limit(10**9)
    with open(AMOSTRA, encoding="utf-8-sig", newline="") as f:
        return [{k: l[k] for k in ("slug", "ano", "estrato", "anotador", "origem")}
                for l in csv.DictReader(f)]


def extrair(revisor: str, leis: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    revisado = json.loads((AVALIACAO / revisor / OURO_REVISADO[revisor]).read_text(encoding="utf-8"))
    ouro, linhas_leis, linhas_ouro = {}, [], []
    for meta in leis:
        slug = meta["slug"]
        html = AVALIACAO / revisor / "leis" / f"{slug}.html"
        lei = fragmentar_referencia(str(html))
        dados = lei.para_dicionario()
        registro = {c: dados[c] for c in CAMPOS}
        registro["dispositivos"] = [dispositivo(d) for d in dados["dispositivos"]]
        ouro[slug] = registro

        antigo = revisado.get(slug)
        dif = diferencas(registro, antigo)
        conferidos = chaves(antigo.get("dispositivos", [])) if antigo else Counter()
        linhas_leis.append({
            "slug": slug, "ano": meta["ano"], "epigrafe": registro["epigrafe"],
            "origem": meta["origem"], "estrato": meta["estrato"],
            "dispositivos": total(registro["dispositivos"]),
            "dispositivos_ouro_revisado": total(antigo["dispositivos"]) if antigo else None,
            "igual_ao_ouro_revisado": "sim" if not dif else "não",
            "diferencas": dif or None,
            "duvida_de_estrutura": None, "revisado_por": None, "status": STATUS,
        })

        # Pré-ordem, na mesma ordem da árvore; a chave casa com chaves() acima.
        def abrir(fragmentos, pais=()):
            for f in fragmentos:
                yield f, pais
                yield from abrir(f.filhos, pais + ((f.tipo.value, normal(f.numero)),))

        for posicao, (f, pais) in enumerate(abrir(lei.dispositivos), start=1):
            k = (pais, f.tipo.value, normal(f.numero), normal(f.rubrica), normal(f.texto))
            if conferidos[k]:
                conferidos[k] -= 1
                no_revisado = "sim"
            else:
                no_revisado = "não"
            linhas_ouro.append({
                "slug": slug, "posicao": posicao, "acao": None, "tipo": f.tipo.value,
                "numero": f.numero, "caminho": f.caminho(), "rubrica": f.rubrica or None,
                "texto": f.texto or None, "observacao": None,
                "no_ouro_revisado": no_revisado, "fonte": "regex LC 95", "status": STATUS,
            })
    return ouro, linhas_leis, linhas_ouro


# --- planilha ----------------------------------------------------------------

def sobre(revisor: str, n_leis: int, iguais: int) -> list[tuple[str, str]]:
    hoje = date.today().strftime("%d/%m/%Y")
    return [
        ("feito por", f"Claude (IA), em {hoje}, com o extrator ajustado à LC 95/1998 (pasta {revisor})."),
        ("status", "Pendente de revisão humana. É uma nova extração, ainda não conferida por pessoa."),
        ("método", "Cada lei foi fragmentada pelo regex do repositório (fragmentador/), já ajustado à "
                   "LC 95/1998, a partir do HTML que está em leis/. As leis são as mesmas da extração "
                   f"anterior: {n_leis} nesta pasta."),
        ("nomenclatura", "Segue a LC 95/1998: epigrafe (art. 4º, antes 'titulo'), ementa (art. 5º), "
                         "preambulo (art. 6º); tipos parte, livro, titulo, capitulo, secao, subsecao "
                         "(art. 10, V a VII), disposicoes (art. 10, VIII), artigo, paragrafo, inciso, "
                         "alinea, item (art. 10, I a IV). O fecho não é nomeado pela LC 95 e fica em 'fecho'."),
        ("convenções", "Texto citado de outra lei fica dentro do dispositivo que o cita. As marcas "
                       "(VETADO), (Revogado) e (NR) são mantidas no texto. Vetos agrupados viram um "
                       "dispositivo com numeração em intervalo ('5º a 7º'). Rótulo fora do texto. "
                       "Fecho e assinaturas fora do último artigo."),
        ("comparação", f"Cada lei foi comparada com o ouro já revisado ({OURO_REVISADO[revisor]}): "
                       f"{iguais} de {n_leis} saíram iguais. Na aba leis, 'igual_ao_ouro_revisado' e "
                       "'diferencas' dizem onde a nova extração diverge; na aba ouro, "
                       "'no_ouro_revisado' = 'não' marca o dispositivo que não está igual no ouro revisado."),
        ("colunas", "Para revisar: corrija no lugar e use 'acao' (manter, corrigir, remover, novo) e "
                    "'observacao'."),
    ]


def gravar_planilha(caminho: pathlib.Path, revisor: str, leis: list[dict], ouro: list[dict]) -> None:
    iguais = sum(l["igual_ao_ouro_revisado"] == "sim" for l in leis)
    with xlsxwriter.Workbook(caminho) as wb:
        cab = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1, "valign": "top"})
        quebra = wb.add_format({"text_wrap": True, "valign": "top"})
        topo = wb.add_format({"valign": "top"})

        def aba(nome, linhas, larguras, quebrar=()):
            ws = wb.add_worksheet(nome)
            colunas = list(linhas[0].keys())
            ws.write_row(0, 0, colunas, cab)
            for i, linha in enumerate(linhas, start=1):
                for j, col in enumerate(colunas):
                    ws.write(i, j, linha[col], quebra if col in quebrar else topo)
            for j, col in enumerate(colunas):
                ws.set_column(j, j, larguras.get(col, 14))
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, len(linhas), len(colunas) - 1)

        aba("sobre", [{"campo": c, "valor": v} for c, v in sobre(revisor, len(leis), iguais)],
            {"campo": 16, "valor": 120}, quebrar={"valor"})
        aba("leis", leis, {"slug": 38, "epigrafe": 42, "origem": 50, "estrato": 20,
                           "diferencas": 60, "duvida_de_estrutura": 40}, quebrar={"diferencas"})
        aba("ouro", ouro, {"slug": 38, "caminho": 32, "rubrica": 30, "texto": 90,
                           "observacao": 30, "status": 24}, quebrar={"texto", "rubrica"})


def main() -> None:
    todas = amostra()
    assert len(todas) == sum(REVISORES.values()), len(todas)
    for revisor, esperado in REVISORES.items():
        leis = [l for l in todas if l["anotador"] == revisor]
        pasta = {p.stem for p in (AVALIACAO / revisor / "leis").glob("*.html")}
        # A divisão tem de ser a mesma da extração anterior.
        assert len(leis) == esperado and {l["slug"] for l in leis} == pasta, revisor

        ouro, linhas_leis, linhas_ouro = extrair(revisor, leis)
        destino = AVALIACAO / revisor / f"ouro_{revisor}_lc95.json"
        destino.write_text(json.dumps(ouro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        gravar_planilha(AVALIACAO / revisor / f"ouro_{revisor}_lc95.xlsx", revisor, linhas_leis, linhas_ouro)

        iguais = sum(l["igual_ao_ouro_revisado"] == "sim" for l in linhas_leis)
        tipos = Counter(l["tipo"] for l in linhas_ouro)
        print(f"{revisor}: {len(ouro)} leis, {len(linhas_ouro)} dispositivos, "
              f"{iguais} iguais ao ouro revisado | {dict(sorted(tipos.items()))}")


if __name__ == "__main__":
    main()
