"""Linha de comando: fragmenta uma lei e mostra ou grava o resultado.

    python -m fragmentador <url-ou-arquivo> [--arvore] [--json saida.json] [--tipo artigo]
"""
from __future__ import annotations

import argparse
import json
import sys

from . import fragmentar_referencia
from .modelos import Fragmento, Lei, Tipo

_RECUO = "    "


def _imprimir_arvore(fragmentos: list[Fragmento], profundidade: int = 0) -> None:
    for f in fragmentos:
        rubrica = f" — {f.rubrica}" if f.rubrica else ""
        texto = f.texto
        if len(texto) > 110:
            texto = texto[:109].rstrip() + "…"
        prefixo = _RECUO * profundidade
        print(f"{prefixo}{f.rotulo}{rubrica}" + (f"  {texto}" if texto else ""))
        _imprimir_arvore(f.filhos, profundidade + 1)


def _resumo(lei: Lei) -> None:
    print(f"Título : {lei.titulo}")
    if lei.ementa:
        print(f"Ementa : {lei.ementa}")
    print(f"Origem : {lei.origem}")
    print("Estruturas encontradas:")
    for tipo, quantidade in lei.contagem().items():
        print(f"{_RECUO}{quantidade:5d}  {tipo}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fragmentador",
        description="Extrai e hierarquiza os dispositivos de uma lei a partir da sua página.",
    )
    parser.add_argument("referencia", help="URL da lei ou caminho de um HTML salvo")
    parser.add_argument("--arvore", action="store_true", help="imprime a árvore de dispositivos")
    parser.add_argument("--json", metavar="ARQUIVO", help="grava o resultado em JSON")
    parser.add_argument(
        "--tipo",
        choices=[t.value for t in Tipo],
        help="lista apenas os fragmentos do tipo indicado",
    )
    args = parser.parse_args(argv)

    try:
        lei = fragmentar_referencia(args.referencia)
    except Exception as erro:  # rede, arquivo ausente, HTML inesperado
        print(f"Falha ao processar {args.referencia}: {erro}", file=sys.stderr)
        return 1

    if args.tipo:
        for f in lei.por_tipo(Tipo(args.tipo)):
            print(f"{f.caminho()}\t{f.texto}")
        return 0

    _resumo(lei)
    if args.arvore:
        print()
        _imprimir_arvore(lei.dispositivos)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as saida:
            json.dump(lei.para_dicionario(), saida, ensure_ascii=False, indent=2)
        print(f"\nJSON gravado em {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
