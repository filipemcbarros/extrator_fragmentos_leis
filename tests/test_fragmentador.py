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

from fragmentador import Tipo, fragmentar, fragmentar_html, fragmentar_referencia  # noqa: E402
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

    def test_artigo_unico(self):
        for texto in [
            "Artigo unico. É declarado feriado...",
            "Artigo único. Fica aberto o credito...",
            "Art. único. Fica o Poder Executivo...",
            "Artigo unico: Não poderá ser ordenado...",
        ]:
            with self.subTest(texto=texto):
                tipo, numero, resto = reconhecer(texto)
                self.assertIs(tipo, Tipo.ARTIGO)
                self.assertEqual(numero, "único")
                self.assertFalse(resto.startswith((".", ":")))
        # Em minúscula é remissão, como no artigo numerado.
        self.assertIsNone(reconhecer("artigo único da Lei nº 93;"))

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

    def test_rotulo_sozinho_na_linha_recebe_a_seguinte(self):
        """Lei 15.348/2026: a alínea vem só com "a)" e o texto parece rótulo."""
        lei = arvore(
            "Art. 9º Ficam revogados:",
            "I - os seguintes dispositivos da Lei nº 14.237:",
            "a)",
            "§ 1º do art. 2º;",
            "b)",
            "art. 6º;",
            "Art. 10. Esta Lei entra em vigor.",
        )
        self.assertEqual([a.numero for a in lei.por_tipo(Tipo.ARTIGO)], ["9º", "10"])
        self.assertEqual(lei.por_tipo(Tipo.PARAGRAFO), [])
        alineas = lei.por_tipo(Tipo.ALINEA)
        self.assertEqual([a.texto for a in alineas], ["§ 1º do art. 2º;", "art. 6º;"])

    def test_artigo_minusculo_e_remissao(self):
        self.assertIsNone(reconhecer("art. 6º da Lei nº 14.237;"))
        self.assertIs(reconhecer("ART. 1º Fica criado...")[0], Tipo.ARTIGO)

    def test_texto_continua_na_linha_seguinte(self):
        lei = arvore("Art. 1º Primeira parte", "segunda parte do caput.")
        self.assertEqual(lei.dispositivos[0].texto, "Primeira parte segunda parte do caput.")

    def test_lei_de_artigo_unico(self):
        """Lei 93/1935: o único artigo não tem número."""
        lei = arvore(
            "Faço saber que o PODER LEGISLATIVO decreta e eu sancciono a seguinte lei:",
            "Artigo unico. É declarado feriado nacional o dia 6 de setembro de 1935.",
            "Rio de Janeiro, 5 de setembro de 1935; 114º da Independencia e 47º da Republica.",
        )
        (artigo,) = lei.por_tipo(Tipo.ARTIGO)
        self.assertEqual(artigo.rotulo, "Art. único")
        self.assertEqual(artigo.texto, "É declarado feriado nacional o dia 6 de setembro de 1935.")
        self.assertTrue(lei.preambulo.startswith("Faço saber"))
        self.assertTrue(lei.fecho.startswith("Rio de Janeiro"))


class TestExtracao(unittest.TestCase):
    def test_rotulo_partido_pela_fonte_e_reunido(self):
        """Lei 6.051/1974: o HTML quebra a linha entre "Art." e o número."""
        lei = fragmentar_html(
            '<div class="textoNorma"><div class="texto"><P>O PRESIDENTE DA REPÚBLICA,<BR>'
            "Faço saber que o CONGRESSO NACIONAL decreta e eu sanciono a seguinte Lei:"
            '<BR><BR>&nbsp;&nbsp;Art. \n\n1º &nbsp;É denominada de "Ponte Marcelino Machado" a ponte.'
            "<BR><BR>&nbsp;&nbsp;Art. \n\n2º &nbsp;Esta Lei \n\nentrará em vigor na data de sua publicação.</P>"
            "<P>Brasília, 30 de maio de 1974; 153º da Independência e 86º da República.</P></div></div>"
        )
        artigos = lei.por_tipo(Tipo.ARTIGO)
        self.assertEqual([a.numero for a in artigos], ["1º", "2º"])
        self.assertEqual(artigos[1].texto, "Esta Lei entrará em vigor na data de sua publicação.")
        self.assertNotIn("Art.", lei.preambulo)

    def test_rotulo_solto_sem_numero_na_linha_seguinte_fica_como_esta(self):
        lei = fragmentar_html(
            '<div class="textoNorma"><div class="texto"><p>Art. 1º Primeira parte, nos termos do<br>'
            "Art.<br>da Constituição.</p></div></div>"
        )
        self.assertEqual(len(lei.por_tipo(Tipo.ARTIGO)), 1)


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
        # Lei promulgada pelo Presidente do Congresso (15.458/2026).
        self.assertTrue(eh_fecho("Brasília, em 3 de julho de 2026; 205º da Independência"))

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
