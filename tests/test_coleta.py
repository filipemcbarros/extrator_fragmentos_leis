"""Testes da coleta em lote, sem rede: só a leitura das páginas.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fragmentador.coleta import (  # noqa: E402
    link_publicacao_original,
    links_de_normas,
    slug_da_norma,
    textos_disponiveis,
    total_anunciado,
)
from fragmentador.fonte import decodificar  # noqa: E402

LEGIN = "https://www2.camara.leg.br/legin/fed/lei/2026/"

BUSCA = f"""
<html><body>
  <span>resultados de 1 a 20 de 206</span>
  <a href="{LEGIN}lei-15332-7-janeiro-2026-798635-norma-pl.html">Lei 15.332</a>
  <a href="{LEGIN}lei-15332-7-janeiro-2026-798635-norma-pl.html">Lei 15.332 (repetido)</a>
  <a href="{LEGIN}lei-15418-28-maio-2026-799193-norma-pl.html">Lei 15.418</a>
  <a href="https://www.camara.leg.br/assuntos/normas">fora do Legin</a>
  <a href="?pagina=2">2</a>
</body></html>
"""

NORMA = """
<html><body>
  <a href="lei-15332-7-janeiro-2026-798635-publicacaooriginal-177718-pl.html">
    <strong> Texto - Publicação Original </strong></a>
  <a href="lei-15332-7-janeiro-2026-798635-veto-1-pl.html">Texto - Veto</a>
  <a href="/biblioteca-e-publicacoes/">Biblioteca e publicações</a>
</body></html>
"""


class TestBusca(unittest.TestCase):
    def test_links_das_normas_sem_repeticao_e_so_do_legin(self):
        self.assertEqual(links_de_normas(BUSCA), [
            f"{LEGIN}lei-15332-7-janeiro-2026-798635-norma-pl.html",
            f"{LEGIN}lei-15418-28-maio-2026-799193-norma-pl.html",
        ])

    def test_total_anunciado(self):
        self.assertEqual(total_anunciado(BUSCA), 206)
        self.assertIsNone(total_anunciado("<html><body>nada</body></html>"))


class TestNorma(unittest.TestCase):
    def test_link_relativo_vira_absoluto(self):
        url = f"{LEGIN}lei-15332-7-janeiro-2026-798635-norma-pl.html"
        self.assertEqual(
            link_publicacao_original(NORMA, url),
            f"{LEGIN}lei-15332-7-janeiro-2026-798635-publicacaooriginal-177718-pl.html",
        )

    def test_norma_sem_publicacao_original(self):
        self.assertIsNone(link_publicacao_original("<html><body></body></html>", LEGIN))

    def test_textos_disponiveis(self):
        self.assertEqual(textos_disponiveis(NORMA),
                         ["Texto - Publicação Original", "Texto - Veto"])

    def test_slug(self):
        self.assertEqual(
            slug_da_norma(f"{LEGIN}lei-15332-7-janeiro-2026-798635-norma-pl.html"),
            "lei-15332-7-janeiro-2026-798635",
        )


class TestDecodificacao(unittest.TestCase):
    def test_utf8_e_latin1(self):
        texto = "Município de Maringá — “Art. 1º”"
        self.assertEqual(decodificar(texto.encode("utf-8")), texto)
        self.assertEqual(decodificar(texto.encode("cp1252")), texto)


if __name__ == "__main__":
    unittest.main()
