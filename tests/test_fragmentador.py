"""Testes do fragmentador.

Rodam com a biblioteca padrão:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fragmentador import Tipo, fragmentar, fragmentar_referencia  # noqa: E402
from fragmentador.extracao import TextoExtraido  # noqa: E402
from fragmentador.rotulos import eh_fecho, reconhecer  # noqa: E402

EXEMPLOS = pathlib.Path(__file__).resolve().parents[1] / "exemplos"


def arvore(*linhas: str):
    return fragmentar(TextoExtraido(linhas=list(linhas)))


class TestReconhecimentoDeRotulos(unittest.TestCase):
    def test_artigo_em_suas_grafias(self):
        for texto, esperado in [
            ("Art. 1º Esta Lei...", "1º"),
            ("Art. 1o Esta Lei...", "1º"),
            ("Art. 10. Esta Lei...", "10"),
            ("Art. 5º-A Acrescido...", "5º-A"),
        ]:
            with self.subTest(texto=texto):
                tipo, numero, _ = reconhecer(texto)
                self.assertIs(tipo, Tipo.ARTIGO)
                self.assertEqual(numero, esperado)

    def test_paragrafo_numerado_e_unico(self):
        tipo, numero, resto = reconhecer("§ 2º É vedado...")
        self.assertIs(tipo, Tipo.PARAGRAFO)
        self.assertEqual(numero, "2º")
        self.assertEqual(resto, "É vedado...")

        tipo, numero, _ = reconhecer("Parágrafo único. No caso...")
        self.assertIs(tipo, Tipo.PARAGRAFO)
        self.assertEqual(numero, "único")

    def test_inciso_exige_travessao(self):
        tipo, numero, _ = reconhecer("III - admitir...")
        self.assertIs(tipo, Tipo.INCISO)
        self.assertEqual(numero, "III")
        # Sem travessão não é inciso: seria confundir texto corrido com rótulo.
        self.assertIsNone(reconhecer("I de janeiro o prazo vence"))

    def test_alinea_e_agrupadores(self):
        self.assertEqual(reconhecer("a) sejam exigidas;")[0], Tipo.ALINEA)
        self.assertEqual(reconhecer("CAPÍTULO II")[0], Tipo.CAPITULO)
        self.assertEqual(reconhecer("SEÇÃO I")[0], Tipo.SECAO)
        self.assertEqual(reconhecer("TÍTULO III")[0], Tipo.TITULO)
        self.assertEqual(reconhecer("SUBSEÇÃO II")[0], Tipo.SUBSECAO)


class TestHierarquia(unittest.TestCase):
    def test_inciso_pende_do_artigo_ou_do_paragrafo(self):
        lei = arvore(
            "Art. 1º Caput do artigo.",
            "I - inciso do artigo;",
            "§ 1º Texto do parágrafo.",
            "II - inciso do parágrafo;",
        )
        artigo = lei.dispositivos[0]
        self.assertEqual([f.tipo for f in artigo.filhos], [Tipo.INCISO, Tipo.PARAGRAFO])
        paragrafo = artigo.filhos[1]
        self.assertEqual([f.tipo for f in paragrafo.filhos], [Tipo.INCISO])
        self.assertEqual(paragrafo.filhos[0].numero, "II")

    def test_alinea_pende_do_inciso_e_item_da_alinea(self):
        lei = arvore(
            "Art. 1º Caput.",
            "I - inciso;",
            "a) alínea;",
            "1. item da alínea;",
        )
        inciso = lei.dispositivos[0].filhos[0]
        alinea = inciso.filhos[0]
        self.assertIs(alinea.tipo, Tipo.ALINEA)
        self.assertEqual([f.tipo for f in alinea.filhos], [Tipo.ITEM])

    def test_item_fora_de_alinea_e_texto(self):
        """'1.' só é item sob alínea; fora disso é numeração do próprio texto."""
        lei = arvore("Art. 1º Caput.", "1. valor de referência apurado;")
        artigo = lei.dispositivos[0]
        self.assertEqual(artigo.filhos, [])
        self.assertIn("valor de referência", artigo.texto)

    def test_agrupadores_encaixam_e_recebem_rubrica(self):
        lei = arvore(
            "TÍTULO I",
            "DAS DISPOSIÇÕES GERAIS",
            "CAPÍTULO I",
            "DO ÂMBITO DE APLICAÇÃO",
            "Art. 1º Caput.",
        )
        titulo = lei.dispositivos[0]
        self.assertIs(titulo.tipo, Tipo.TITULO)
        self.assertEqual(titulo.rubrica, "DAS DISPOSIÇÕES GERAIS")
        capitulo = titulo.filhos[0]
        self.assertIs(capitulo.tipo, Tipo.CAPITULO)
        self.assertEqual(capitulo.rubrica, "DO ÂMBITO DE APLICAÇÃO")
        self.assertIs(capitulo.filhos[0].tipo, Tipo.ARTIGO)

    def test_caminho_acumula_a_hierarquia(self):
        lei = arvore("CAPÍTULO I", "DAS GERAIS", "Art. 1º Caput.", "§ 1º P.", "II - inc;", "b) al;")
        alinea = [f for f in lei.percorrer() if f.tipo is Tipo.ALINEA][0]
        self.assertEqual(alinea.caminho(), "CAPITULO I, Art. 1º, § 1º, II, b)")

    def test_texto_continua_na_linha_seguinte(self):
        lei = arvore("Art. 1º Primeira parte", "segunda parte do caput.")
        self.assertEqual(lei.dispositivos[0].texto, "Primeira parte segunda parte do caput.")


class TestCitacaoDeAlteracao(unittest.TestCase):
    def test_texto_citado_nao_vira_dispositivo(self):
        lei = arvore(
            "Art. 1º A Lei X passa a vigorar acrescida do seguinte artigo:",
            '"Art. 337-E. Admitir contratação direta ilegal:',
            "Pena - reclusão.",
            'Art. 337-F. Outro crime." (NR)',
            "Art. 2º Esta Lei entra em vigor.",
        )
        numeros = [a.numero for a in lei.por_tipo(Tipo.ARTIGO)]
        self.assertEqual(numeros, ["1º", "2º"])
        self.assertIn("337-E", lei.dispositivos[0].texto)

    def test_citacao_sem_fechamento_termina_na_sequencia(self):
        """A fonte nem sempre fecha as aspas; a numeração contínua desempata."""
        lei = arvore(
            "Art. 177. A Lei Y passa a vigorar com a seguinte redação:",
            '"Art. 1.048 .......................',
            "IV - texto alterado;",
            "Art. 178. O Título II passa a vigorar...",
        )
        self.assertEqual([a.numero for a in lei.por_tipo(Tipo.ARTIGO)], ["177", "178"])


class TestFecho(unittest.TestCase):
    def test_reconhece_local_e_data(self):
        self.assertTrue(eh_fecho("Brasília, 30 de agosto de 1970; 149º da Independência"))
        self.assertTrue(eh_fecho("Sala das Sessões, em 1º de abril"))

    def test_nao_confunde_cidade_no_meio_do_texto(self):
        self.assertFalse(eh_fecho("Art. 2º As obras em Brasília observarão o disposto nesta Lei."))

    def test_nao_sofre_retrocesso_catastrofico(self):
        """Linha longa sem vírgula já travou o reconhecedor; aqui fica o limite."""
        linha = "Art. 1º " + ("palavra " * 400)
        inicio = time.perf_counter()
        eh_fecho(linha)
        self.assertLess(time.perf_counter() - inicio, 0.5)

    def test_fecho_encerra_o_corpo(self):
        lei = arvore(
            "Art. 3º Revogam-se as disposições em contrário.",
            "Brasília, 30 de agosto de 1970; 149º da Independência.",
            "EMÍLIO G. MÉDICI",
        )
        self.assertEqual(lei.dispositivos[0].texto, "Revogam-se as disposições em contrário.")
        self.assertIn("EMÍLIO", lei.fecho)


@unittest.skipUnless((EXEMPLOS / "lei-14133-2021.html").exists(), "exemplos não baixados")
class TestLeisReais(unittest.TestCase):
    """Conferência de ponta a ponta sobre páginas reais do acervo da Câmara."""

    def test_lei_5603_1970(self):
        lei = fragmentar_referencia(str(EXEMPLOS / "lei-5603-1970.html"))
        self.assertEqual(lei.titulo, "LEI Nº 5.603, DE 30 DE AGOSTO DE 1970")
        self.assertIn("Via Dom Bosco", lei.ementa)
        self.assertEqual(lei.contagem(), {"artigo": 3})

    def test_lei_8666_1993(self):
        lei = fragmentar_referencia(str(EXEMPLOS / "lei-8666-1993.html"))
        contagem = lei.contagem()
        self.assertEqual(contagem["artigo"], 125)   # publicação original vai até o art. 125
        self.assertEqual(contagem["inciso"], 274)
        self.assertEqual(contagem["alinea"], 55)
        self.assertEqual(contagem["capitulo"], 6)

    def test_lei_14133_2021_sequencia_completa(self):
        lei = fragmentar_referencia(str(EXEMPLOS / "lei-14133-2021.html"))
        numeros = [a.numero for a in lei.por_tipo(Tipo.ARTIGO)]
        self.assertEqual(len(numeros), 194)
        base = [int(n.split("º")[0].split("-")[0]) for n in numeros]
        self.assertEqual(base, list(range(1, 195)), "a sequência de artigos deve ser contínua")
        # Os arts. 337-E a 337-P são do Código Penal, citados pelo art. 178.
        self.assertFalse([n for n in numeros if n.startswith("337")])

    def test_lei_14133_hierarquia(self):
        lei = fragmentar_referencia(str(EXEMPLOS / "lei-14133-2021.html"))
        pais = {}

        def anda(f, p=None):
            pais[id(f)] = p
            for c in f.filhos:
                anda(c, f)

        for d in lei.dispositivos:
            anda(d)

        for f in lei.percorrer():
            pai = pais[id(f)]
            if f.tipo is Tipo.ALINEA:
                self.assertIs(pai.tipo, Tipo.INCISO)
            if f.tipo is Tipo.PARAGRAFO:
                self.assertIs(pai.tipo, Tipo.ARTIGO)
            if f.tipo is Tipo.INCISO:
                self.assertIn(pai.tipo, {Tipo.ARTIGO, Tipo.PARAGRAFO})


if __name__ == "__main__":
    unittest.main()
