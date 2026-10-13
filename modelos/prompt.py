"""O prompt: a tarefa, o formato da resposta e dois exemplos.

O texto é o mesmo para os três modelos e vai inteiro na mensagem do usuário —
o Gemma não aceita mensagem de sistema, e assim nenhum modelo recebe instrução
por via diferente dos outros.
"""
from __future__ import annotations

import json

INSTRUCOES = """\
Você recebe o texto de uma lei brasileira, em {descricao}, e deve devolvê-lo fragmentado em seus dispositivos, em JSON.

A hierarquia segue a Lei Complementar 95/1998:
- agrupadores, do maior para o menor: parte > livro > titulo > capitulo > secao > subsecao;
- artigo ("Art. 1º", "Art. 10."), dentro do agrupador aberto, ou na raiz se não houver;
- paragrafo ("§ 1º", "Parágrafo único") e inciso ("I -", "II -") pendem do artigo;
- o inciso que vem depois de um parágrafo pende desse parágrafo;
- alinea ("a)", "b)") pende do inciso; item ("1.", "2.") pende da alínea.

Responda com um único objeto JSON, sem comentários e sem cercas de código, com as chaves:
- "titulo": o nome da lei ("LEI Nº 1.234, DE 5 DE MAIO DE 1990");
- "ementa": o resumo que vem logo abaixo do título;
- "preambulo": o que vem entre a ementa e o primeiro dispositivo ("O PRESIDENTE DA REPÚBLICA Faço saber...");
- "fecho": local, data e assinaturas, depois do último dispositivo;
- "dispositivos": a lista dos dispositivos de primeiro nível.

Cada dispositivo é um objeto com:
- "tipo": parte, livro, titulo, capitulo, secao, subsecao, artigo, paragrafo, inciso, alinea ou item;
- "numero": a numeração como está na lei, sem o rótulo: "1º", "10", "5º-A", "II", "a", "único";
- "rubrica": só nos agrupadores, o nome que os acompanha ("DAS DISPOSIÇÕES GERAIS");
- "texto": o texto do dispositivo sem o rótulo; no artigo, é o caput; no agrupador, fica vazio;
- "filhos": os dispositivos subordinados, na ordem; omita a chave quando não houver.

Regras:
- copie o texto exatamente como está, sem corrigir grafia, resumir ou traduzir;
- todo o texto da lei deve aparecer na resposta, cada trecho uma única vez;
- crie só os dispositivos que estão escritos na lei: nenhum dispositivo vazio, e nenhum agrupador (parte, livro, titulo, capitulo, secao, subsecao) que a lei não traga. Na lei sem agrupadores, os artigos vão direto em "dispositivos";
- o artigo sem parágrafos nem incisos não tem "filhos";
- quando a lei altera outra e transcreve entre aspas o texto alterado, a transcrição inteira é texto do artigo que faz a alteração: não crie dispositivos para o que está entre aspas.
"""

_DESCRICAO = {"html": "HTML", "texto": "texto corrido, uma linha por dispositivo"}

#: O caso mais comum do acervo: poucos artigos, sem agrupador e sem desdobramento.
#: Só com o exemplo completo, o modelo copiava o esqueleto dele — envolvia toda
#: lei num agrupador e pendurava inciso e parágrafo vazios no primeiro artigo.
_EXEMPLO_MINIMO_ENTRADA = {
    "html": """\
<h1>LEI Nº 8.888, DE 7 DE JUNHO DE 1994</h1>
<div class="textoNorma"><p class="ementa">Institui o Dia Nacional do Livro.</p>
<div class="texto"><p>O PRESIDENTE DA REPÚBLICA<br>Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:</p>
<p>Art. 1º É instituído o Dia Nacional do Livro, a ser comemorado anualmente em 29 de outubro.</p>
<p>Art. 2º Esta Lei entra em vigor na data de sua publicação.</p>
<p>Brasília, 7 de junho de 1994; 173º da Independência e 106º da República.<br>FULANO DE TAL<br>Beltrano de Tal</p></div></div>""",
    "texto": """\
LEI Nº 8.888, DE 7 DE JUNHO DE 1994
Institui o Dia Nacional do Livro.
O PRESIDENTE DA REPÚBLICA
Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:
Art. 1º É instituído o Dia Nacional do Livro, a ser comemorado anualmente em 29 de outubro.
Art. 2º Esta Lei entra em vigor na data de sua publicação.
Brasília, 7 de junho de 1994; 173º da Independência e 106º da República.
FULANO DE TAL
Beltrano de Tal""",
}

_EXEMPLO_MINIMO_SAIDA = {
    "titulo": "LEI Nº 8.888, DE 7 DE JUNHO DE 1994",
    "ementa": "Institui o Dia Nacional do Livro.",
    "preambulo": "O PRESIDENTE DA REPÚBLICA Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:",
    "fecho": "Brasília, 7 de junho de 1994; 173º da Independência e 106º da República. FULANO DE TAL Beltrano de Tal",
    "dispositivos": [
        {"tipo": "artigo", "numero": "1º",
         "texto": "É instituído o Dia Nacional do Livro, a ser comemorado anualmente em 29 de outubro."},
        {"tipo": "artigo", "numero": "2º", "texto": "Esta Lei entra em vigor na data de sua publicação."},
    ],
}

_EXEMPLO_ENTRADA = {
    "html": """\
<h1>LEI Nº 9.999, DE 3 DE MARÇO DE 1999</h1>
<div class="textoNorma"><p class="ementa">Dispõe sobre o registro de embarcações e altera a Lei nº 1.111, de 1950.</p>
<div class="texto"><p>O PRESIDENTE DA REPÚBLICA<br>Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:</p>
<p>CAPÍTULO I<br>DO REGISTRO</p>
<p>Art. 1º O registro de embarcações é obrigatório:<br>I - para as de pesca;<br>II - para as de transporte:<br>a) de carga;<br>b) de passageiros.<br>Parágrafo único. O registro é gratuito.</p>
<p>Art. 2º O art. 4º da Lei nº 1.111, de 1950, passa a vigorar com a seguinte redação:<br>"Art. 4º O prazo é de trinta dias.<br>§ 1º O prazo pode ser prorrogado." (NR)</p>
<p>Art. 3º Esta Lei entra em vigor na data de sua publicação.</p>
<p>Brasília, 3 de março de 1999; 178º da Independência e 111º da República.<br>FULANO DE TAL<br>Beltrano de Tal</p></div></div>""",
    "texto": """\
LEI Nº 9.999, DE 3 DE MARÇO DE 1999
Dispõe sobre o registro de embarcações e altera a Lei nº 1.111, de 1950.
O PRESIDENTE DA REPÚBLICA
Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:
CAPÍTULO I
DO REGISTRO
Art. 1º O registro de embarcações é obrigatório:
I - para as de pesca;
II - para as de transporte:
a) de carga;
b) de passageiros.
Parágrafo único. O registro é gratuito.
Art. 2º O art. 4º da Lei nº 1.111, de 1950, passa a vigorar com a seguinte redação:
"Art. 4º O prazo é de trinta dias.
§ 1º O prazo pode ser prorrogado." (NR)
Art. 3º Esta Lei entra em vigor na data de sua publicação.
Brasília, 3 de março de 1999; 178º da Independência e 111º da República.
FULANO DE TAL
Beltrano de Tal""",
}

_EXEMPLO_SAIDA = {
    "titulo": "LEI Nº 9.999, DE 3 DE MARÇO DE 1999",
    "ementa": "Dispõe sobre o registro de embarcações e altera a Lei nº 1.111, de 1950.",
    "preambulo": "O PRESIDENTE DA REPÚBLICA Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:",
    "fecho": "Brasília, 3 de março de 1999; 178º da Independência e 111º da República. FULANO DE TAL Beltrano de Tal",
    "dispositivos": [
        {"tipo": "capitulo", "numero": "I", "rubrica": "DO REGISTRO", "texto": "", "filhos": [
            {"tipo": "artigo", "numero": "1º", "texto": "O registro de embarcações é obrigatório:", "filhos": [
                {"tipo": "inciso", "numero": "I", "texto": "para as de pesca;"},
                {"tipo": "inciso", "numero": "II", "texto": "para as de transporte:", "filhos": [
                    {"tipo": "alinea", "numero": "a", "texto": "de carga;"},
                    {"tipo": "alinea", "numero": "b", "texto": "de passageiros."},
                ]},
                {"tipo": "paragrafo", "numero": "único", "texto": "O registro é gratuito."},
            ]},
            {"tipo": "artigo", "numero": "2º", "texto": (
                "O art. 4º da Lei nº 1.111, de 1950, passa a vigorar com a seguinte redação: "
                '"Art. 4º O prazo é de trinta dias. § 1º O prazo pode ser prorrogado." (NR)')},
            {"tipo": "artigo", "numero": "3º", "texto": "Esta Lei entra em vigor na data de sua publicação."},
        ]},
    ],
}


_PRIMEIRO_TRECHO = """\
Atenção: esta lei é longa e foi dividida em {trechos} trechos. Este é o primeiro. Fragmente só o que está nele; o fecho vem em outro trecho, deixe "fecho" vazio.
"""

_TRECHO_SEGUINTE = """\
Atenção: esta lei é longa e foi dividida em {trechos} trechos. Este é o trecho {trecho}, que começa no meio da lei.
- Deixe "titulo", "ementa" e "preambulo" vazios.{sem_fecho}
- Se o trecho começar por texto que continua o dispositivo anterior, antes de qualquer rótulo, ponha esse texto na chave "continuacao".
- O dispositivo cujo pai ficou em trecho anterior (um inciso sem o seu artigo, por exemplo) vai direto em "dispositivos".
"""


#: Os exemplos do prompt, na ordem: (entrada por formato, resposta).
EXEMPLOS = [
    (_EXEMPLO_MINIMO_ENTRADA, _EXEMPLO_MINIMO_SAIDA),
    (_EXEMPLO_ENTRADA, _EXEMPLO_SAIDA),
]


def montar(entrada: str, formato: str = "html", trecho: int = 1, trechos: int = 1) -> str:
    """Prompt completo para uma lei, ou um trecho dela, já preparada por `entrada`."""
    exemplos = "".join(
        f"\nExemplo {i} de entrada:\n{lei[formato]}\n"
        f"\nResposta do exemplo {i}:\n{json.dumps(resposta, ensure_ascii=False, separators=(',', ':'))}\n"
        for i, (lei, resposta) in enumerate(EXEMPLOS, 1))
    aviso = ""
    if trechos > 1 and trecho == 1:
        aviso = "\n" + _PRIMEIRO_TRECHO.format(trechos=trechos)
    elif trechos > 1:
        sem_fecho = "" if trecho == trechos else '\n- O fecho vem em outro trecho: deixe "fecho" vazio.'
        aviso = "\n" + _TRECHO_SEGUINTE.format(trecho=trecho, trechos=trechos, sem_fecho=sem_fecho)
    return (
        INSTRUCOES.format(descricao=_DESCRICAO[formato])
        + exemplos
        + aviso
        + f"\nAgora {'a lei' if trechos == 1 else 'o trecho'} a fragmentar:\n{entrada}\n"
    )
