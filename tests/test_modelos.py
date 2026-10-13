"""Testes do pós-processamento e da comparação dos modelos de linguagem.

Não carregam modelo algum: exercitam o que acontece com a resposta depois que
ela chega — leitura do JSON, normalização e medidas contra o regex.
"""
import json
import unittest

from fragmentador.extracao import TextoExtraido
from fragmentador.fragmentador import fragmentar
from modelos.analise import calibrar, classificar_corte
from modelos.comparar import achatar, comparar_lei
from modelos.entrada import dividir, preparar
from modelos.resposta import extrair_json, normalizar, separar_trechos
from modelos.prompt import EXEMPLOS, montar

RESPOSTA = {
    "titulo": "LEI Nº 1, DE 1º DE JANEIRO DE 2000",
    "ementa": "Dispõe sobre testes.",
    "preambulo": "O PRESIDENTE DA REPÚBLICA",
    "fecho": "Brasília, 1º de janeiro de 2000.",
    "dispositivos": [
        {"tipo": "capitulo", "numero": "I", "rubrica": "DAS REGRAS", "texto": "", "filhos": [
            {"tipo": "artigo", "numero": "1º", "texto": "Caput:", "filhos": [
                {"tipo": "inciso", "numero": "I", "texto": "primeiro;"},
                {"tipo": "paragrafo", "numero": "único", "texto": "Único."},
            ]},
        ]},
    ],
}


class LeituraDaResposta(unittest.TestCase):
    def test_json_limpo(self):
        objeto, estado = extrair_json(json.dumps(RESPOSTA))
        self.assertEqual((objeto, estado), (RESPOSTA, "ok"))

    def test_cerca_de_codigo_e_conversa_em_volta(self):
        resposta = "Aqui está:\n```json\n" + json.dumps(RESPOSTA) + "\n```\nEspero ter ajudado."
        self.assertEqual(extrair_json(resposta), (RESPOSTA, "ok"))

    def test_resposta_truncada_aproveita_o_que_esta_completo(self):
        inteira = json.dumps(RESPOSTA, ensure_ascii=False)
        objeto, estado = extrair_json(inteira[:inteira.index("Único")])
        self.assertEqual(estado, "reparado")
        artigo = objeto["dispositivos"][0]["filhos"][0]
        self.assertEqual([f["tipo"] for f in artigo["filhos"]], ["inciso"])

    def test_chave_dentro_de_texto_nao_confunde_o_reparo(self):
        objeto, estado = extrair_json('{"titulo": "a } b", "dispositivos": [{"tipo": "artigo"}, {"tip')
        self.assertEqual(estado, "reparado")
        self.assertEqual(objeto["titulo"], "a } b")

    def test_sem_json(self):
        self.assertEqual(extrair_json("Não consigo fragmentar."), (None, "invalido"))


class Normalizacao(unittest.TestCase):
    def test_deriva_rotulo_caminho_e_contagem(self):
        dados, avisos = normalizar(RESPOSTA, origem="o", norma="n")
        self.assertEqual(avisos, 0)
        self.assertEqual(dados["contagem"], {"artigo": 1, "capitulo": 1, "inciso": 1, "paragrafo": 1})
        paragrafo = dados["dispositivos"][0]["filhos"][0]["filhos"][1]
        self.assertEqual(paragrafo["rotulo"], "Parágrafo único")
        self.assertEqual(paragrafo["caminho"], "CAPITULO I, Art. 1º, Parágrafo único")

    def test_limpa_rotulo_repetido_no_numero_e_tipo_acentuado(self):
        resposta = {"dispositivos": [
            {"tipo": "Artigo", "numero": "Art. 2o.", "texto": "x", "filhos": [
                {"tipo": "parágrafo", "numero": "§ 1°", "texto": "y"},
                {"tipo": "alínea", "numero": "a)", "texto": "z"},
                {"tipo": "paragrafo", "numero": "Parágrafo único", "texto": "w"},
            ]},
        ]}
        dados, _ = normalizar(resposta)
        artigo = dados["dispositivos"][0]
        self.assertEqual(artigo["numero"], "2º")
        self.assertEqual([f["numero"] for f in artigo["filhos"]], ["1º", "a", "único"])

    def test_tipo_desconhecido_e_descartado_e_os_filhos_sobem(self):
        resposta = {"dispositivos": [
            {"tipo": "anexo", "filhos": [{"tipo": "artigo", "numero": "1º", "texto": "x"}]}, "solto"]}
        dados, avisos = normalizar(resposta)
        self.assertEqual(avisos, 2)
        self.assertEqual([d["caminho"] for d in dados["dispositivos"]], ["Art. 1º"])


class LeiEmTrechos(unittest.TestCase):
    def test_lei_curta_nao_e_dividida(self):
        self.assertEqual(dividir("Art. 1º Um.<br>Art. 2º Dois.", len, 100), ["Art. 1º Um.<br>Art. 2º Dois."])

    def test_divide_nas_quebras_sem_perder_texto(self):
        lei = "".join(f"Art. {i}. Texto do artigo.<br>" for i in range(1, 21))
        trechos = dividir(lei, len, 100)
        self.assertGreater(len(trechos), 1)
        self.assertEqual("".join(trechos), lei)
        self.assertTrue(all(len(t) <= 100 and t.endswith("<br>") for t in trechos))

    def test_linha_maior_que_o_limite_e_partida_por_palavras(self):
        linha = "palavra " * 200
        trechos = dividir(linha, len, 100)
        self.assertTrue(all(len(t) <= 100 for t in trechos))
        self.assertEqual("".join(trechos).split(), linha.split())

    def test_emenda_pendura_o_orfao_no_dispositivo_aberto(self):
        primeiro = {"titulo": "LEI", "dispositivos": [
            {"tipo": "capitulo", "numero": "I", "texto": "", "filhos": [
                {"tipo": "artigo", "numero": "1º", "texto": "Caput:", "filhos": [
                    {"tipo": "inciso", "numero": "I", "texto": "primeiro, que"}]}]}]}
        segundo = {"continuacao": "continua aqui;", "fecho": "Brasília.", "dispositivos": [
            {"tipo": "inciso", "numero": "II", "texto": "segundo."},
            {"tipo": "artigo", "numero": "2º", "texto": "Outro."},
            {"tipo": "capitulo", "numero": "II", "texto": ""}]}
        dados, _ = normalizar([primeiro, segundo])
        self.assertEqual([d["caminho"] for d in achatar(dados)], [
            "capitulo i", "capitulo i, art. 1º", "capitulo i, art. 1º, i",
            "capitulo i, art. 1º, ii", "capitulo i, art. 2º", "capitulo ii"])
        self.assertEqual(achatar(dados)[2]["texto"], "primeiro, que continua aqui;")
        self.assertEqual((dados["titulo"], dados["fecho"]), ("LEI", "Brasília."))

    def test_trecho_sem_json_nao_derruba_os_outros(self):
        dados, _ = normalizar([RESPOSTA, None, {"dispositivos": [{"tipo": "artigo", "numero": "2º"}]}])
        self.assertEqual(dados["contagem"]["artigo"], 2)

    def test_bruto_da_lei_dividida_e_separado_pelas_marcas(self):
        bruto = '===== trecho 1 de 2 =====\n{"a": 1}\n===== trecho 2 de 2 =====\n{"b": 2}\n'
        self.assertEqual(separar_trechos(bruto), ['{"a": 1}\n', '{"b": 2}\n'])
        self.assertEqual(separar_trechos('{"a": 1}'), ['{"a": 1}'])

    def test_lei_inteira_fica_com_a_hierarquia_do_modelo(self):
        """A regra de pilha só vale na emenda: não conserta o que o modelo montou."""
        resposta = {"dispositivos": [{"tipo": "artigo", "numero": "1º"}, {"tipo": "inciso", "numero": "I"}]}
        self.assertEqual([d["caminho"] for d in normalizar(resposta)[0]["dispositivos"]], ["Art. 1º", "I"])

    def test_prompt_do_trecho_avisa_onde_ele_esta(self):
        self.assertNotIn("trechos", montar("x"))
        self.assertIn("Este é o primeiro", montar("x", "html", 1, 3))
        self.assertIn("continuacao", montar("x", "html", 2, 3))
        self.assertNotIn('deixe "fecho" vazio', montar("x", "html", 3, 3))


class Comparacao(unittest.TestCase):
    def setUp(self):
        self.regex, _ = normalizar(RESPOSTA)

    def test_arvores_iguais(self):
        medidas = comparar_lei(self.regex, normalizar(RESPOSTA)[0])
        self.assertEqual((medidas["id_f1"], medidas["caminho_f1"], medidas["identica"]), (1.0, 1.0, 1))

    def test_dispositivo_no_pai_errado_pesa_so_na_hierarquia(self):
        errada = json.loads(json.dumps(RESPOSTA))
        artigo = errada["dispositivos"][0]["filhos"][0]
        # O parágrafo sai do artigo e vai pender do inciso.
        artigo["filhos"][0]["filhos"] = [artigo["filhos"].pop(1)]
        medidas = comparar_lei(self.regex, normalizar(errada)[0])
        self.assertEqual(medidas["id_f1"], 1.0)
        self.assertEqual(medidas["caminho_r"], 0.75)
        self.assertEqual(medidas["identica"], 0)

    def test_rubrica_deixada_no_texto_nao_conta_como_erro_de_texto(self):
        outra = json.loads(json.dumps(RESPOSTA))
        capitulo = outra["dispositivos"][0]
        capitulo["texto"], capitulo["rubrica"] = capitulo["rubrica"], None
        self.assertEqual(comparar_lei(self.regex, normalizar(outra)[0])["texto_exato"], 1.0)

    def test_json_invalido_zera_as_medidas(self):
        medidas = comparar_lei(self.regex, None)
        self.assertEqual((medidas["id_f1"], medidas["caminho_f1"], medidas["titulo_igual"]), (0.0, 0.0, 0))


class Prompt(unittest.TestCase):
    def test_exemplos_do_prompt_sao_o_que_o_regex_devolve(self):
        """O exemplo ensina o formato; se divergisse do regex, ensinaria a discordar."""
        for entrada, resposta in EXEMPLOS:
            titulo, ementa, *linhas = entrada["texto"].split("\n")
            regex = fragmentar(TextoExtraido(titulo=titulo, ementa=ementa, linhas=linhas)).para_dicionario()
            medidas = comparar_lei(regex, normalizar(resposta)[0])
            self.assertEqual(medidas["identica"], 1)
            self.assertEqual([medidas[f"{c}_igual"] for c in ("titulo", "ementa", "preambulo", "fecho")], [1] * 4)

    def test_os_dois_formatos_de_cada_exemplo_trazem_a_mesma_lei(self):
        for entrada, _ in EXEMPLOS:
            pagina = f"<html><body>{entrada['html']}</body></html>"
            self.assertEqual(preparar(pagina, "texto"), entrada["texto"])

    def test_exemplo_minimo_nao_tem_agrupador_nem_filhos(self):
        minimo = EXEMPLOS[0][1]
        self.assertEqual([d["tipo"] for d in minimo["dispositivos"]], ["artigo", "artigo"])
        self.assertFalse(any("filhos" in d for d in minimo["dispositivos"]))

    def test_prompt_traz_a_lei(self):
        self.assertTrue(montar("<p>Art. 1º Teste.</p>", "html").rstrip().endswith("<p>Art. 1º Teste.</p>"))


class Analise(unittest.TestCase):
    def test_resposta_valida_nao_e_corte(self):
        self.assertIsNone(classificar_corte(json.dumps(RESPOSTA)))

    def test_cortes_sao_classificados_pelo_fim_da_resposta(self):
        inicio = json.dumps(RESPOSTA)[:-2]
        artigo = '{"tipo":"artigo","numero":"9","texto":"' + "Texto de um artigo qualquer, bem comprido. " * 4 + '"},'
        self.assertEqual(classificar_corte(inicio + "\n  " * 100), "laço de espaços")
        self.assertEqual(classificar_corte(inicio + ',{"texto":"' + "\\n " * 100), "laço dentro de um texto")
        self.assertEqual(classificar_corte(inicio + "." * 300), "repetição curta")
        self.assertEqual(classificar_corte(inicio + artigo * 5), "repetição de trecho longo")
        self.assertEqual(classificar_corte(inicio + ',{"tipo":"artigo","numero":"2º","texto":"Cortado no meio de'), "outro")

    def test_razao_de_caracteres_por_token_sai_da_fronteira(self):
        leis = {f"curta{i}": {"dividida": False} for i in range(50)} | {f"media{i}": {"dividida": True} for i in range(50)}
        caracteres = {s: 6000 + 60 * int(s[5:]) if s.startswith("curta") else 9050 + 60 * int(s[5:]) for s in leis}
        caracteres["longa"] = 90000
        # As inteiras vão até 8.940 caracteres e as demais começam em 9.050: o corte fica entre os dois.
        self.assertTrue(8940 / 3000 <= calibrar(leis, ["longa"], caracteres) < 9050 / 3000)


if __name__ == "__main__":
    unittest.main()
