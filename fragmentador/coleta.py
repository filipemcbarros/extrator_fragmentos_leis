"""Coleta em lote: todas as leis de um ano, da busca da Câmara aos JSONs.

O caminho até o texto tem três páginas:

1. a busca (`camara.leg.br/legislacao/busca`), paginada a partir de 1, com 20
   resultados por página e o total anunciado em "resultados de 1 a 20 de 206";
2. a página da norma (`…-norma-pl.html`), que só traz metadados e os links;
3. a publicação original (`…-publicacaooriginal-<id>-pl.html`), que é o texto
   fragmentado. O `<id>` não deriva da URL da norma: é preciso abrir a norma.

Cada lei vira um JSON em `<destino>/<ano>/json/`, e o HTML da publicação fica
guardado em `<destino>/<ano>/html/`, o que permite refazer a fragmentação sem
voltar à rede. O `indice.json` registra o desfecho de cada lei, inclusive as que
falharam. Uma nova execução pula as leis já coletadas, de modo que uma coleta
interrompida continua de onde parou.

    python -m fragmentador.coleta --ano 2026
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

from lxml import html as lhtml
from requests import Request

from .fonte import baixar, ler
from .fragmentador import fragmentar_html

BUSCA = "https://www.camara.leg.br/legislacao/busca"

_TOTAL = re.compile(r"resultados\s+de\s+\d+\s+a\s+\d+\s+de\s+(\d+)", re.I)


@dataclass
class Registro:
    """Desfecho da coleta de uma lei, como fica no índice."""

    slug: str
    norma: str
    publicacao: str | None = None
    arquivo: str | None = None
    titulo: str | None = None
    contagem: dict | None = None
    erro: str | None = None


# --- leitura das páginas ---------------------------------------------------

def parametros_busca(ano: int, pagina: int, tipo: str = "Lei Ordinária") -> dict:
    # A ordenação padrão, por relevância, não é estável entre páginas: em 2026
    # repetia leis e deixava 12 das 206 de fora. Por data a listagem fecha.
    return {
        "geral": "",
        "ano": str(ano),
        "abrangencia": "Legislação Federal",
        "ordenacao": "data:ASC",
        "tipo": tipo,
        "origem": "",
        "situacao": "",
        "numero": "",
        "pagina": str(pagina),
    }


def links_de_normas(html_busca: str) -> list[str]:
    """Links das normas numa página de resultados, na ordem e sem repetição."""
    arvore = lhtml.fromstring(html_busca)
    vistos: dict[str, None] = {}
    for href in arvore.xpath('//a[contains(@href, "-norma-")]/@href'):
        if "/legin/" in href:
            vistos.setdefault(href.strip(), None)
    return list(vistos)


def total_anunciado(html_busca: str) -> int | None:
    m = _TOTAL.search(lhtml.fromstring(html_busca).text_content())
    return int(m.group(1)) if m else None


def link_publicacao_original(html_norma: str, url_norma: str) -> str | None:
    """Link absoluto para "Texto - Publicação Original", se a norma o tiver."""
    arvore = lhtml.fromstring(html_norma)
    for href in arvore.xpath('//a[contains(@href, "publicacaooriginal")]/@href'):
        return urljoin(url_norma, href.strip())
    return None


def textos_disponiveis(html_norma: str) -> list[str]:
    """Rótulos dos links "Texto - …" da norma, para registrar o que existe."""
    arvore = lhtml.fromstring(html_norma)
    rotulos = (" ".join(a.text_content().split()) for a in arvore.xpath("//a[@href]"))
    return [r for r in rotulos if r.lower().startswith("texto")]


def slug_da_norma(url_norma: str) -> str:
    """'…/lei-15332-7-janeiro-2026-798635-norma-pl.html' -> 'lei-15332-7-janeiro-2026-798635'."""
    nome = url_norma.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"-norma-[a-z]+\.html?$", "", nome)


# --- rede --------------------------------------------------------------------

class Cliente:
    """Baixa páginas com pausa entre pedidos e novas tentativas em falha."""

    def __init__(self, pausa: float = 1.0, tentativas: int = 3):
        self.pausa = pausa
        self.tentativas = tentativas
        self._ultimo = 0.0

    def get(self, url: str, params: dict | None = None) -> str:
        if params:
            url = Request("GET", url, params=params).prepare().url
        erro: Exception | None = None
        for tentativa in range(1, self.tentativas + 1):
            espera = self.pausa - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            try:
                return baixar(url)
            except Exception as e:  # rede instável ou 5xx: vale insistir
                erro = e
                time.sleep(self.pausa * 2 ** tentativa)
            finally:
                self._ultimo = time.monotonic()
        raise RuntimeError(f"{url}: {erro}")


def listar_normas(ano: int, cliente: Cliente, tipo: str = "Lei Ordinária",
                  log=print) -> tuple[list[str], int | None]:
    """Percorre a busca inteira e devolve os links das normas e o total anunciado."""
    normas: dict[str, None] = {}
    total: int | None = None
    pagina = 1
    while True:
        conteudo = cliente.get(BUSCA, parametros_busca(ano, pagina, tipo))
        if total is None:
            total = total_anunciado(conteudo)
        achados = links_de_normas(conteudo)
        novos = [l for l in achados if l not in normas]
        log(f"  busca página {pagina}: {len(achados)} links, {len(novos)} novos")
        if not novos:
            break
        for l in novos:
            normas[l] = None
        if total is not None and len(normas) >= total:
            break
        pagina += 1
    return list(normas), total


# --- coleta ------------------------------------------------------------------

def _gravar_json(caminho: pathlib.Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def coletar_norma(url_norma: str, pastas: dict[str, pathlib.Path],
                  cliente: Cliente, forcar: bool = False) -> Registro:
    slug = slug_da_norma(url_norma)
    registro = Registro(slug=slug, norma=url_norma)
    destino_json = pastas["json"] / f"{slug}.json"
    destino_html = pastas["html"] / f"{slug}.html"

    try:
        if destino_html.exists() and not forcar:
            # O HTML guardado basta para (re)fragmentar; a URL vem do JSON anterior.
            conteudo = ler(destino_html)
            if destino_json.exists():
                anterior = json.loads(destino_json.read_text(encoding="utf-8"))
                registro.publicacao = anterior.get("origem")
        else:
            html_norma = cliente.get(url_norma)
            registro.publicacao = link_publicacao_original(html_norma, url_norma)
            if not registro.publicacao:
                outros = textos_disponiveis(html_norma)
                registro.erro = ("página da norma sem link para a publicação original"
                                 + (f"; disponíveis: {', '.join(outros)}" if outros else ""))
                return registro
            conteudo = cliente.get(registro.publicacao)
            destino_html.write_text(conteudo, encoding="utf-8")

        lei = fragmentar_html(conteudo, origem=registro.publicacao or "")
        dados = lei.para_dicionario()
        dados["norma"] = url_norma
        _gravar_json(destino_json, dados)

        registro.arquivo = str(destino_json.relative_to(pastas["raiz"])).replace("\\", "/")
        registro.titulo = lei.titulo
        registro.contagem = lei.contagem()
        if not registro.contagem.get("artigo"):
            registro.erro = "nenhum artigo reconhecido"
    except Exception as e:
        registro.erro = f"{type(e).__name__}: {e}"
    return registro


def coletar_ano(ano: int, destino: str | pathlib.Path = "coleta", *,
                tipo: str = "Lei Ordinária", pausa: float = 1.0,
                forcar: bool = False, limite: int | None = None, log=print) -> dict:
    raiz = pathlib.Path(destino) / str(ano)
    pastas = {"raiz": raiz, "json": raiz / "json", "html": raiz / "html"}
    for p in pastas.values():
        p.mkdir(parents=True, exist_ok=True)

    cliente = Cliente(pausa=pausa)
    log(f"Listando {tipo} de {ano}…")
    normas, total = listar_normas(ano, cliente, tipo, log=log)
    log(f"{len(normas)} normas encontradas (a busca anuncia {total}).")
    if limite:
        normas = normas[:limite]

    registros: list[Registro] = []
    for i, url in enumerate(normas, 1):
        r = coletar_norma(url, pastas, cliente, forcar=forcar)
        registros.append(r)
        situacao = f"ERRO: {r.erro}" if r.erro else f"{(r.contagem or {}).get('artigo', 0)} artigos"
        log(f"[{i:3d}/{len(normas)}] {r.slug}  {situacao}")

    indice = {
        "ano": ano,
        "tipo": tipo,
        "total_anunciado": total,
        "normas_listadas": len(normas),
        "coletadas": sum(1 for r in registros if r.arquivo),
        "com_erro": sum(1 for r in registros if r.erro),
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "leis": [asdict(r) for r in registros],
    }
    _gravar_json(raiz / "indice.json", indice)
    return indice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fragmentador.coleta",
        description="Coleta e fragmenta todas as leis de um ano a partir da busca da Câmara.",
    )
    parser.add_argument("--ano", type=int, required=True)
    parser.add_argument("--destino", default="coleta", help="pasta raiz da coleta (padrão: coleta)")
    parser.add_argument("--tipo", default="Lei Ordinária", help='tipo na busca (padrão: "Lei Ordinária")')
    parser.add_argument("--pausa", type=float, default=1.0, help="segundos entre pedidos (padrão: 1)")
    parser.add_argument("--forcar", action="store_true", help="baixa de novo mesmo o que já foi coletado")
    parser.add_argument("--limite", type=int, help="processa só as N primeiras normas (teste)")
    args = parser.parse_args(argv)

    indice = coletar_ano(args.ano, args.destino, tipo=args.tipo, pausa=args.pausa,
                         forcar=args.forcar, limite=args.limite)
    print(f"\n{indice['coletadas']} JSONs gravados, {indice['com_erro']} com erro. "
          f"Índice em {pathlib.Path(args.destino) / str(args.ano) / 'indice.json'}")
    if indice["total_anunciado"] and indice["normas_listadas"] != indice["total_anunciado"] and not args.limite:
        print(f"Atenção: a busca anuncia {indice['total_anunciado']} normas, "
              f"mas {indice['normas_listadas']} foram listadas.", file=sys.stderr)
    return 0 if not indice["com_erro"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
