# Avaliação dos métodos de fragmentação (dataset ouro)

Material para montar o dataset ouro e comparar os três LLMs (Qwen, Gemma e Llama) com o regex.

## Amostra

- População: 15.754 leis com até 9.000 tokens, respondidas pelos três modelos.
- Tamanho pela fórmula de Cochran, com 5% de erro e 95% de confiança (p = 0,5) e correção para população finita: **376 leis**.
- Estratificada por época (1891-1945, 1946-1988, 1989-2026) e por tamanho (tercis do nº de dispositivos do regex), 9 estratos com alocação proporcional. Cada lei tem peso N_h / n_h (coluna `peso`).
- Semente 2026, para o sorteio ser reprodutível com `montar_amostra.py`.

## Divisão da anotação

As 376 leis foram divididas em três pastas, uma por anotador (`Paulo/`, `Pedro/`, `Filipe/`), cada uma com a planilha `anotacao_<nome>.xlsx` e o HTML das leis em `leis/`. Cada lei foi extraída para uma só pasta (sem dupla anotação) e depois conferida por outro membro do grupo (revisão pareada):

| Pasta (anotador) | Leis | Revisor |
|---|---|---|
| `Filipe/` | 125 | Paulo |
| `Paulo/` | 126 | Pedro |
| `Pedro/` | 125 | Filipe (1ª revisão) e Paulo (2ª, correção do fecho em 3 leis) |

## Dataset ouro final

As três pastas revisadas foram juntadas em `ouro_final/`, que é o ouro usado na avaliação:

- `ouro_final/ouro_lc95.json`: as 376 leis, `{slug: {epigrafe, ementa, preambulo, fecho, dispositivos}}`, no mesmo formato dos `ouro_<anotador>_lc95.json` e na ordem de `amostra/amostra_leis.csv`.
- `ouro_final/ouro_lc95.xlsx`: gerada do JSON, só para consulta. Abas `sobre`, `leis` (época, tamanho, estrato, peso, anotador, revisor, campos da lei, nº de dispositivos, se Qwen, Gemma e Llama responderam, nota do revisor) e `dispositivos` (uma linha por dispositivo, com o caminho, ex.: "Art. 1º, § 1º").
- `ouro_final/consolidar_ouro.py`: refaz os dois arquivos a partir de `<anotador>/ouro_<anotador>_lc95.json`. Roda da raiz: `python avaliacao/ouro_final/consolidar_ouro.py`.

O JSON é a fonte. Uma correção entra no `ouro_<anotador>_lc95.json` da pasta e o script é rodado de novo; a planilha não deve ser editada.

Antes de gravar, o script confere, e não grava nada se algo falhar:

- as 376 leis da amostra, cada uma em uma só pasta, com o conteúdo idêntico ao da pasta de origem;
- os cinco campos da lei, nenhum vazio, e a epígrafe com o número e o ano do slug;
- tipos da LC 95, agrupadores com rubrica, nenhum dispositivo sem texto, hierarquia coerente (parágrafo, inciso, alínea e item abaixo do nível do pai) e nenhum artigo repetido no mesmo nível;
- fecho fora dos dispositivos e nenhum resto de HTML (`-->`).

Correções feitas depois das revisões, em 07/11/2026: o fecho que estava dentro do último artigo foi para o campo `fecho` na Lei 7.176/1983 (Filipe) e saiu do último artigo, onde estava repetido, nas Leis 3.099/1957, 8.621/1993 e 8.640/1993 (Pedro); o `-->` foi retirado do fecho das Leis 7.283/1984 e 7.358/1985 (Filipe).

Os modelos responderam 369 (Qwen), 355 (Gemma) e 323 (Llama) das 376 leis com o prompt LC 95 (`../modelos/resultados/lc95/`). O `modelos/comparar.py` compara os modelos com o regex e pede o `caminho` de cada nó, que o ouro não traz; a comparação com o ouro precisa montar esse caminho, como faz a aba `dispositivos`.

## Métrica

- Para cada dispositivo (artigo, parágrafo, inciso, alínea, item), similaridade de Levenshtein normalizada entre o texto do método e o texto do ouro.
- Média por lei e, depois, por modelo, com intervalo de confiança de 95%.
- Comparação entre os métodos nas mesmas leis: teste de Friedman e, em seguida, Wilcoxon pareado com correção de Holm.

## Arquivos

- `montar_amostra.py`: sorteia a amostra e gera os arquivos abaixo. Roda a partir da raiz do repositório.
- `amostra/amostra_leis.csv`: uma linha por lei, com a lei bruta e a saída de cada método.
- `amostra/dispositivos_longo.csv`: uma linha por dispositivo, alinhado entre os métodos.
- `amostra/ouro_rascunho.csv`: a árvore do regex em linhas, ponto de partida para os anotadores corrigirem.
- `amostra_ouro.ipynb` e `ver_leis.ipynb`: notebooks para montar a amostra e visualizar as leis.
- `piloto/`: piloto com 5 leis.
- `<anotador>/ouro_<anotador>_lc95.json` e `.xlsx`: o ouro revisado de cada pasta, fonte do `ouro_final/`.
- `extrair_ouro_lc95.py`: refaz a extração das 376 leis com o extrator ajustado à LC 95/1998, com a mesma divisão por revisor, e grava `<revisor>/ouro_<revisor>_lc95.json` e `.xlsx`. Compara cada lei com o ouro já revisado (`ouro_<revisor>.json`; `paulo_ouro_v3.json` no caso do Paulo), que não é alterado.

## Saídas dos modelos

- As colunas `json_qwen`, `json_gemma`, `json_llama` e afins de `amostra/amostra_leis.csv` vêm das rodadas com o prompt anterior à LC 95/1998.
- As respostas dos três modelos com o prompt ajustado à LC 95/1998, para estas mesmas 376 leis, estão em `../modelos/resultados/lc95/<modelo>_lc95_restrita/` (`bruto/`, `json/` e `registro.csv`). Os notebooks de `../modelos/notebooks/` leem a lista de leis deste CSV (opção `AMOSTRA`). Ver [../modelos/README.md](../modelos/README.md).

**Atenção:** o mini-ouro do piloto (`piloto/`) foi feito pelo Claude, não por um anotador humano. É provisório e serve só para testar a métrica; não deve entrar nos resultados.
