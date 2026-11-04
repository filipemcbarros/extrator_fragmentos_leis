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

from fragmentador import Lei, Tipo, fragmentar, fragmentar_html, fragmentar_referencia  # noqa: E402
from fragmentador.modelos import campo_da_lei  # noqa: E402
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


class TestAgrupadoresLC95(unittest.TestCase):
    """LC 95/1998, art. 10, V a VIII: agrupadores e a sua numeração."""

    def test_numeracoes_previstas_e_das_leis_antigas(self):
        for linha, tipo, numero in [
            ("PARTE GERAL", Tipo.PARTE, "GERAL"),
            ("PARTE ESPECIAL", Tipo.PARTE, "ESPECIAL"),
            ("PARTE PRIMEIRA", Tipo.PARTE, "PRIMEIRA"),
            ("LIVRO I", Tipo.LIVRO, "I"),
            ("LIVRO COMPLEMENTAR", Tipo.LIVRO, "COMPLEMENTAR"),
            ("TÍTULO ÚNICO", Tipo.TITULO, "ÚNICO"),
            ("CAPÍTULO IV-A", Tipo.CAPITULO, "IV-A"),
            ("CAPITULO DÉCIMO PRIMEIRO", Tipo.CAPITULO, "DÉCIMO PRIMEIRO"),
            ("Seção II", Tipo.SECAO, "II"),
            ("Seção 1ª", Tipo.SECAO, "1ª"),
            ("Subseção Única", Tipo.SUBSECAO, "Única"),
        ]:
            with self.subTest(linha=linha):
                self.assertEqual(reconhecer(linha)[:2], (tipo, numero))

    def test_caixa_irregular_da_fonte(self):
        """'CAPíTULO VI', 'Título ii': erros de digitação do acervo."""
        self.assertEqual(reconhecer("CAPíTULO VI")[:2], (Tipo.CAPITULO, "VI"))
        self.assertEqual(reconhecer("Título ii")[:2], (Tipo.TITULO, "II"))
        self.assertEqual(reconhecer("Capítulo I I")[:2], (Tipo.CAPITULO, "II"))

    def test_texto_corrido_nao_vira_agrupador(self):
        for linha in [
            "parte do valor arrecadado",   # minúscula: continuação de texto
            "Título de eleitor expedido",   # numeração ausente
            "Capítulo VI desta Lei",        # remissão
            "Seção de Pessoal",
            "Capítulo 08 - Frutos Comestíveis",  # linha de tabela
            "Livro de Presença",
        ]:
            with self.subTest(linha=linha):
                self.assertIsNone(reconhecer(linha))

    def test_rubrica_na_mesma_linha_nao_cola_no_numero(self):
        self.assertEqual(reconhecer("CAPÍTULO III DISPOSIÇÕES TRANSITÓRIAS E FINAIS"),
                         (Tipo.CAPITULO, "III", "DISPOSIÇÕES TRANSITÓRIAS E FINAIS"))
        self.assertEqual(reconhecer("Capítulo I - Da Definição"), (Tipo.CAPITULO, "I", "Da Definição"))
        lei = arvore("Seção II Da Fixação da Despesa", "Art. 1º Caput.")
        self.assertEqual((lei.dispositivos[0].numero, lei.dispositivos[0].rubrica),
                         ("II", "Da Fixação da Despesa"))

    def test_rubrica_fora_da_caixa_alta_na_linha_seguinte(self):
        lei = arvore("Capítulo I", "Da Definição de Microempresa", "Art. 1º Caput.")
        capitulo = lei.dispositivos[0]
        self.assertEqual(capitulo.rubrica, "Da Definição de Microempresa")
        self.assertEqual(capitulo.texto, "")
        self.assertIs(capitulo.filhos[0].tipo, Tipo.ARTIGO)

    def test_parte_livro_titulo_capitulo_secao_subsecao(self):
        lei = arvore(
            "PARTE ESPECIAL", "LIVRO I", "DO DIREITO DAS OBRIGAÇÕES", "TÍTULO I",
            "DAS MODALIDADES", "CAPÍTULO I", "DAS OBRIGAÇÕES DE DAR", "Seção I",
            "Das Obrigações de Dar Coisa Certa", "Subseção I", "Disposição comum",
            "Art. 233. A obrigação de dar coisa certa...",
        )
        artigo = lei.por_tipo(Tipo.ARTIGO)[0]
        self.assertEqual(artigo.caminho(),
                         "PARTE ESPECIAL, LIVRO I, TITULO I, CAPITULO I, SECAO I, SUBSECAO I, Art. 233")
        self.assertEqual(lei.por_tipo(Tipo.SECAO)[0].rubrica, "Das Obrigações de Dar Coisa Certa")


class TestDisposicoes(unittest.TestCase):
    """LC 95/1998, art. 10, VIII: Disposições Preliminares, Gerais, Finais ou Transitórias."""

    def test_reconhece_as_quatro_e_as_combinacoes(self):
        for linha in ["DISPOSIÇÕES PRELIMINARES", "DISPOSIÇÃO PRELIMINAR", "Disposições Gerais",
                      "DISPOSIÇÕES GERAES", "DAS DISPOSIÇÕES FINAIS E TRANSITÓRIAS",
                      "Disposições Gerais, Transitórias e Finais", "Disposições preliminares:"]:
            with self.subTest(linha=linha):
                self.assertEqual(reconhecer(linha), (Tipo.DISPOSICOES, None, linha))
        self.assertIsNone(reconhecer("Disposições diversas sobre o tema"))
        self.assertIsNone(reconhecer("disposições finais desta Lei"))

    def test_sem_capitulo_agrupam_artigos(self):
        lei = arvore(
            "Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:",
            "DISPOSIÇÕES PRELIMINARES", "Art. 1º Primeiro.",
            "DISPOSIÇÕES FINAIS", "Art. 2º Segundo.",
        )
        self.assertEqual(lei.preambulo,
                         "Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:")
        self.assertEqual([(d.tipo, d.rubrica) for d in lei.dispositivos], [
            (Tipo.DISPOSICOES, "DISPOSIÇÕES PRELIMINARES"), (Tipo.DISPOSICOES, "DISPOSIÇÕES FINAIS")])
        self.assertEqual(lei.dispositivos[1].filhos[0].caminho(), "DISPOSIÇÕES FINAIS, Art. 2º")

    def test_logo_abaixo_do_capitulo_e_rubrica_dele(self):
        lei = arvore("CAPÍTULO VI", "DISPOSIÇÕES FINAIS", "Art. 9º Texto.")
        self.assertEqual(lei.por_tipo(Tipo.DISPOSICOES), [])
        self.assertEqual(lei.dispositivos[0].rubrica, "DISPOSIÇÕES FINAIS")

    def test_depois_do_capitulo_e_irma_dele(self):
        lei = arvore("CAPÍTULO V", "DO ACESSO", "Art. 22. Texto.", "DISPOSIÇÕES FINAIS", "Art. 23. Texto.")
        self.assertEqual([d.tipo for d in lei.dispositivos], [Tipo.CAPITULO, Tipo.DISPOSICOES])
        self.assertEqual(lei.por_tipo(Tipo.ARTIGO)[1].caminho(), "DISPOSIÇÕES FINAIS, Art. 23")

    def test_no_titulo_recem_aberto_fica_dentro_dele(self):
        """Lei 8.080/1990: 'TÍTULO II' / 'DISPOSIÇÃO PRELIMINAR' / 'Art. 4º'."""
        lei = arvore("TÍTULO II", "DO SISTEMA ÚNICO DE SAÚDE", "DISPOSIÇÃO PRELIMINAR",
                     "Art. 4º Texto.", "CAPÍTULO I", "DOS OBJETIVOS", "Art. 5º Texto.")
        titulo = lei.dispositivos[0]
        self.assertEqual([f.tipo for f in titulo.filhos], [Tipo.DISPOSICOES, Tipo.CAPITULO])


class TestItens(unittest.TestCase):
    """LC 95/1998, art. 10, II e IV: o item, em algarismo arábico, desdobra a alínea."""

    def test_sequencia_de_itens_sob_alinea(self):
        lei = arvore("Art. 1º Caput.", "I - inciso;", "a) alínea:", "1. um;", "2. dois;", "3. três.")
        alinea = lei.por_tipo(Tipo.ALINEA)[0]
        self.assertEqual([(f.numero, f.texto) for f in alinea.filhos],
                         [("1", "um;"), ("2", "dois;"), ("3", "três.")])
        self.assertEqual(alinea.filhos[2].caminho(), "Art. 1º, I, a), 3.")

    def test_grafias_do_item(self):
        for linha, numero in [("1. um;", "1"), ("2) dois;", "2"), ("3 - três;", "3"), ("1º) o curso", "1º")]:
            with self.subTest(linha=linha):
                self.assertEqual(reconhecer(linha)[:2], (Tipo.ITEM, numero))

    def test_item_sob_inciso_em_enumeracao_anunciada(self):
        """Lei 7.519/1986, art. 10: itens sob inciso, comuns antes da LC 95."""
        lei = arvore(
            "Art. 10. As infrações sujeitam o infrator às seguintes penalidades:",
            "I - pelo descumprimento das obrigações acessórias:",
            "1. normas do item I - multa de 3 valores;",
            "2. normas do item II - multa de 1 valor;",
            "II - outra hipótese;",
        )
        inciso = lei.por_tipo(Tipo.INCISO)[0]
        self.assertEqual([f.numero for f in inciso.filhos], ["1", "2"])
        self.assertEqual(lei.por_tipo(Tipo.INCISO)[1].numero, "II")

    def test_item_sob_paragrafo_com_travessao(self):
        """Lei 5.985/1973: '1 - Técnico Judiciário' sob o parágrafo único."""
        lei = arvore("Art. 1º Caput.", "Parágrafo único. São Categorias Funcionais:",
                     "1 - Técnico Judiciário;", "2 - Taquígrafo Judiciário.")
        paragrafo = lei.por_tipo(Tipo.PARAGRAFO)[0]
        self.assertEqual([(f.tipo, f.numero) for f in paragrafo.filhos],
                         [(Tipo.ITEM, "1"), (Tipo.ITEM, "2")])

    def test_numeracao_fora_de_enumeracao_e_texto(self):
        # Sob artigo a LC 95 não prevê item.
        lei = arvore("Art. 1º Caput:", "1. valor de referência;")
        self.assertEqual(lei.dispositivos[0].filhos, [])
        # Sob inciso sem dois-pontos, nem começando do 1, é linha de tabela.
        lei = arvore("Art. 1º Caput.", "I - Pessoal Civil", "04 - Justiça Eleitoral")
        self.assertEqual(lei.por_tipo(Tipo.ITEM), [])
        self.assertIn("04 - Justiça Eleitoral", lei.por_tipo(Tipo.INCISO)[0].texto)
        # Sequência quebrada: o "5." não continua o item 1.
        lei = arvore("Art. 1º Caput.", "I - inciso:", "1. um;", "5. outro número")
        self.assertEqual([f.numero for f in lei.por_tipo(Tipo.ITEM)], ["1"])

    def test_alinea_depois_do_item_volta_ao_inciso(self):
        lei = arvore("Art. 1º Caput.", "I - inciso:", "1. um:", "a) alínea;")
        inciso = lei.por_tipo(Tipo.INCISO)[0]
        self.assertEqual([f.tipo for f in inciso.filhos], [Tipo.ITEM, Tipo.ALINEA])


class TestSituacaoNormativa(unittest.TestCase):
    """Vetos e revogações: o rótulo é reconhecido e o texto fica como está."""

    def test_veto_agrupado_de_artigos_e_paragrafos(self):
        self.assertEqual(reconhecer("Arts. 5º a 7º (VETADOS)."), (Tipo.ARTIGO, "5º a 7º", "(VETADOS)."))
        self.assertEqual(reconhecer("Arts. 3º e 4º - Vetados."), (Tipo.ARTIGO, "3º e 4º", "Vetados."))
        self.assertEqual(reconhecer("§§ 5° - 6º - 7º - VETADO."),
                         (Tipo.PARAGRAFO, "5º - 6º - 7º", "VETADO."))
        self.assertEqual(reconhecer("§§ 1º e 2º (Revogados)."),
                         (Tipo.PARAGRAFO, "1º e 2º", "(Revogados)."))
        # Sem a marca de situação é remissão ou tabela.
        self.assertIsNone(reconhecer("Arts. 82 e 83, para os fins"))
        self.assertIsNone(reconhecer("§§ 1º, 2º e 5º do art. 1º;"))

    def test_rotulo_e_sequencia_do_veto_agrupado(self):
        lei = arvore(
            "Art. 4º Texto.", "Arts. 5º a 7º (VETADOS).", "§§ 1º e 2º (VETADOS).",
            "Art. 8º A Lei X passa a vigorar com a seguinte redação:",
            '"Art. 1.048 ........', "Art. 9º Esta Lei entra em vigor.",
        )
        artigos = lei.por_tipo(Tipo.ARTIGO)
        self.assertEqual([a.rotulo for a in artigos], ["Art. 4º", "Arts. 5º a 7º", "Art. 8º", "Art. 9º"])
        self.assertEqual(artigos[1].filhos[0].rotulo, "§§ 1º e 2º")
        self.assertEqual(artigos[1].texto, "(VETADOS).")

    def test_inciso_vetado_sem_travessao(self):
        self.assertEqual(reconhecer("IV (VETADO);"), (Tipo.INCISO, "IV", "(VETADO);"))
        self.assertIsNone(reconhecer("IV de janeiro de cada ano"))

    def test_marcas_preservadas_no_texto(self):
        lei = arvore(
            "Art. 1º Caput.",
            "I - (revogado);",
            "II - texto alterado (Redação dada pela Lei nº 9.999, de 1999);",
            "§ 1º (VETADO).",
            "Art. 2º (Declarado inconstitucional pela ADI nº 1.000).",
        )
        textos = [f.texto for f in lei.percorrer()]
        self.assertEqual(textos, [
            "Caput.", "(revogado);", "texto alterado (Redação dada pela Lei nº 9.999, de 1999);",
            "(VETADO).", "(Declarado inconstitucional pela ADI nº 1.000)."])


class TestNomenclaturaDaLei(unittest.TestCase):
    """Campos da lei com os nomes da LC 95/1998: epígrafe (art. 4º), ementa, preâmbulo."""

    def test_json_traz_epigrafe(self):
        lei = fragmentar(TextoExtraido(titulo="LEI Nº 1, DE 2 DE JANEIRO DE 2000",
                                       ementa="Dispõe sobre testes.", linhas=["Art. 1º Caput."]))
        dados = lei.para_dicionario()
        self.assertEqual(dados["epigrafe"], "LEI Nº 1, DE 2 DE JANEIRO DE 2000")
        self.assertNotIn("titulo", dados)
        self.assertEqual(list(dados)[:4], ["epigrafe", "ementa", "preambulo", "fecho"])

    def test_titulo_continua_como_sinonimo(self):
        lei = Lei(epigrafe="LEI Nº 1")
        self.assertEqual(lei.titulo, "LEI Nº 1")
        lei.titulo = "LEI Nº 2"
        self.assertEqual(lei.epigrafe, "LEI Nº 2")

    def test_le_json_antigo_e_novo(self):
        self.assertEqual(campo_da_lei({"titulo": "LEI Nº 1"}, "epigrafe"), "LEI Nº 1")
        self.assertEqual(campo_da_lei({"epigrafe": "LEI Nº 2", "titulo": "x"}, "epigrafe"), "LEI Nº 2")
        self.assertEqual(campo_da_lei({"ementa": "E"}, "ementa"), "E")
        self.assertEqual(campo_da_lei(None, "epigrafe"), "")


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
        self.assertEqual(lei.epigrafe, "LEI Nº 5.603, DE 30 DE AGOSTO DE 1970")
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
