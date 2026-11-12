# Fragmentação de leis com modelos de linguagem

Esta pasta guarda a segunda fase do projeto. Na primeira, o pacote `fragmentador` dividiu as 16.418 leis ordinárias federais do acervo (1891 a 2026) em dispositivos — artigos, parágrafos, incisos, alíneas, itens e agrupadores — usando expressões regulares (regex). Aqui, as mesmas leis são entregues a modelos de linguagem, e o resultado é comparado com o do regex.

O relatório completo está em [relatorios/relatorio_tecnico_acervo.docx](relatorios/relatorio_tecnico_acervo.docx). Este arquivo é o resumo.

## Objetivo

Responder a duas perguntas:

1. Um modelo de linguagem pré-treinado, recebendo o mesmo HTML que o regex recebe, produz a mesma estrutura de dispositivos?
2. Entre três modelos abertos de tamanho parecido, qual se sai melhor, e a que custo?

O regex é a referência, não um gabarito: as medidas dizem o quanto o modelo concorda com ele, não o quanto acerta.

## Como funciona

1. **Entrada.** De cada página da lei recorta-se o título e o bloco `div.textoNorma`, sem menus, scripts e atributos.
2. **Prompt.** Um texto fixo, igual para todas as leis e modelos: a hierarquia da Lei Complementar 95/1998, o formato da resposta e dois exemplos. A lei entra no fim.
3. **Geração.** O modelo devolve um JSON com `epigrafe`, `ementa`, `preambulo`, `fecho` e a árvore de `dispositivos`, com os nomes da LC 95/1998 (a epígrafe é o art. 4º; os tipos incluem `disposicoes`, do art. 10, VIII). As respostas das rodadas anteriores trazem `titulo` no lugar de `epigrafe` e continuam legíveis na comparação.
4. **Comparação.** A resposta é convertida para o formato do JSON do regex e as duas árvores são comparadas, lei a lei.

## Modelos

| Modelo | Identificador no Hugging Face | Parâmetros |
|---|---|---|
| Qwen 2.5 7B | `Qwen/Qwen2.5-7B-Instruct` | 7 bilhões |
| Gemma 3 12B | `google/gemma-3-12b-it` | 12 bilhões |
| Llama 3.1 8B | `meta-llama/Llama-3.1-8B-Instruct` | 8 bilhões |

Os três rodaram em precisão cheia. Gemma e Llama exigem aceitar a licença e um token do Hugging Face.

## Plataforma e ferramentas

| Item | O que foi usado |
|---|---|
| Execução dos modelos | Google Colab Pro, GPU A100 de 40 GB (os primeiros testes foram na T4 gratuita) |
| Motor de geração | vLLM 0.31.0, com pedidos em paralelo (blocos de 256) |
| Armazenamento das respostas | Google Drive |
| Linguagem | Python 3.12 |
| Bibliotecas | `vllm` (geração), `lxml` (recorte do HTML), biblioteca padrão (`json`, `csv`, `difflib`, `unittest`) |
| Comparação e análise | máquina local, sem GPU |

## Técnicas

- **Prompt com dois exemplos** (um mínimo e um completo) e geração determinística, com temperatura zero.
- **Decodificação restrita:** o motor só deixa o modelo escrever um JSON que obedeça a um esquema. Garante a sintaxe, não o conteúdo.
- **Divisão em trechos:** a lei que não cabe na janela é cortada em trechos de até 3.000 tokens, nas quebras de linha do HTML e nunca nos rótulos dos dispositivos. Cada trecho é um pedido, e as árvores são emendadas depois.
- **Reparo:** da resposta cortada pelo limite de tokens aproveita-se o que veio completo.
- **Medidas:** precisão, revocação e F1 de identificação (tipo e número do dispositivo) e de hierarquia (caminho completo), árvore idêntica, igualdade de texto e fidelidade ao texto da página.

## Experimentos realizados

| Etapa | O que foi feito | Leis |
|---|---|---|
| Testes de montagem | Llama quantizado em 4 bits na T4, para ajustar prompt e programa | 30, depois 300 |
| Amostra | Os três modelos em modo livre e em modo restrito, sobre uma amostra fixa | 300 |
| Leis inteiras | Os três modelos, modo restrito, leis de até 3.000 tokens | cerca de 14.600 por modelo |
| Gramática sem espaço livre | Teste no Llama para evitar respostas em laço; piorou o resultado e foi descartado | 271 |
| Leis divididas | Os três modelos, modo restrito, leis de 3.000 a 9.000 tokens, em trechos | cerca de 1.150 por modelo |
| Leis restantes | Acima de 9.000 tokens; **não processadas** | cerca de 630 por modelo |
| Prompt da LC 95/1998 | Os três modelos, modo restrito, com o prompt e o esquema ajustados à LC 95/1998, só sobre a amostra da avaliação (`avaliacao/amostra/amostra_leis.csv`) | 376 |

## Principais resultados

Sobre as 15.754 leis que os três modelos responderam (96% do acervo):

| Medida | Qwen | Gemma | Llama |
|---|---|---|---|
| JSON válido | 98,9% | 95,8% | 85,5% |
| Identificação dos dispositivos (F1) | 0,88 | 0,86 | 0,71 |
| Hierarquia (F1), todas as leis | 0,82 | 0,81 | 0,49 |
| Hierarquia (F1), leis inteiras | 0,84 | 0,84 | 0,52 |
| Hierarquia (F1), leis divididas | 0,46 | 0,34 | 0,07 |
| Árvore idêntica à do regex | 45% | 52% | 20% |

- **A concordância cai com o tamanho da lei.** Nas leis de até 500 tokens, mais da metade do conjunto, Qwen e Gemma passam de 0,93 de hierarquia; nas divididas, a árvore quase nunca coincide inteira.
- **Qwen e Gemma empatam nas leis pequenas; o Qwen é melhor nas maiores.** O Llama fica atrás em tudo.
- **Parte das respostas entra em laço** (quase sempre de espaços em branco) e é cortada pelo limite de tokens: 0,7% das leis inteiras no Qwen, 3,1% no Gemma e 10,4% no Llama, e mais nos trechos das leis divididas.
- **Cada modelo tem um erro típico.** O Qwen achata a árvore, deixando parágrafos e incisos fora dos artigos; o Llama aninha artigos dentro de artigos; o Gemma cria itens e agrupadores que a lei não tem.
- **O texto é copiado com fidelidade:** 93% a 94% dos dispositivos trazem o texto literal da lei.

Esses números são das rodadas com o prompt anterior à LC 95/1998.

## Rodada com o prompt da LC 95/1998

Depois do ajuste do extrator e do prompt à LC 95/1998, os três modelos rodaram de novo, em modo restrito, só sobre as 376 leis da amostra da avaliação (ver [../avaliacao/README.md](../avaliacao/README.md)). As respostas estão em `resultados/lc95/`, em pastas próprias (`<modelo>_lc95_restrita`), separadas das rodadas antigas.

| Medida | Qwen | Gemma | Llama |
|---|---|---|---|
| Leis respondidas | 376 | 376 | 376 |
| JSON válido | 369 (98%) | 355 (94%) | 323 (86%) |
| Cortadas pelo limite de tokens | 7 | 21 | 53 |
| Divididas em trechos | 28 | 25 | 28 |

Nas mesmas 376 leis, com o prompt anterior, eram válidas 372 respostas no Qwen, 360 no Gemma e 314 no Llama, e cortadas 4, 16 e 62. As contagens acima são as do `registro.csv`, antes do reparo das respostas cortadas.

As respostas cortadas são, na maioria, laços, e não leis longas demais. Os números são de uma leitura do fim de cada resposta bruta:

| Por que cortou | Qwen | Gemma | Llama |
|---|---|---|---|
| Laço de espaços e quebras de linha | 4 | 9 | 40 |
| Laço de estrutura (agrupadores vazios aninhados) | 0 | 8 | 3 |
| Resposta longa | 3 | 4 | 10 |

Para uma segunda tentativa só nessas leis, os notebooks têm `REFAZER = True`:
- lê do `registro.csv` desta rodada as leis cortadas;
- dobra a janela, para 24.576 tokens;
- sobe o teto da resposta (`FATOR`) de 2,2 para 4 vezes o trecho;
- grava em `<modelo>_lc95_restrita_refeitas/`, sem tocar a rodada original.

A geração é determinística, então o laço de espaços se repete com qualquer teto. Para atacá-lo, ligue também `SEM_ESPACOS`, que grava em `_sem_espacos_refeitas`. Essa gramática já foi descartada no acervo inteiro (ver a tabela de experimentos); aqui ela vale só como segunda tentativa, e a escolha precisa ser registrada na avaliação.

A segunda tentativa, sem `SEM_ESPACOS`, rodou em 10/11/2026 e está em `resultados/lc95/<modelo>_lc95_restrita_refeitas/`. Só as respostas longas foram resolvidas; todos os laços se repetiram, como previsto:

| Medida | Qwen | Gemma | Llama |
|---|---|---|---|
| Leis refeitas | 7 | 21 | 53 |
| Resolvidas (JSON válido) | 3 | 3 | 6 |
| Ainda cortadas: laço de espaços e quebras de linha | 4 | 10 | 46 |
| Ainda cortadas: laço de estrutura | 0 | 8 | 1 |
| JSON válido somando as duas tentativas | 372 (99%) | 358 (95%) | 329 (88%) |
| Pedidos | 14 | 33 | 81 |
| Tempo de geração | 2 min 44 s | 11 min 13 s | 11 min 07 s |
| Tokens/s | 254 | 269 | 625 |

A classificação do que continua cortado vem da leitura do fim de cada trecho bruto e difere um pouco da tabela anterior: algumas respostas que pareciam longas tinham o laço num trecho do meio, ou um laço de `\t` escrito dentro do texto. Os segundos estão em `resultados/lc95/tempos.csv`; as três somam 25 min 04 s, cerca de 2,2 unidades e R$ 1,28 (5,3 unidades por hora, R$ 58 por 100 unidades). As pastas `_refeitas` trazem só as 81 leis refeitas; nenhum script junta ainda as duas tentativas, e a rodada original continua como estava.

| Modelo | Tempo de geração | Tokens/s | Unidades | Custo |
|---|---|---|---|---|
| Qwen 2.5 7B | 3 min 25 s | 1.972 | 0,30 | R$ 0,18 |
| Gemma 3 12B | 16 min 18 s | 396 | 1,44 | R$ 0,84 |
| Llama 3.1 8B | 8 min 22 s | 973 | 0,74 | R$ 0,43 |
| **Total** | **28 min 05 s** | | **2,48** | **R$ 1,44** |

Os segundos são os impressos pelos notebooks e estão em `resultados/lc95/tempos.csv`. Como nas rodadas anteriores, não entram a instalação, a carga do modelo nem o tempo parado da sessão. Cada rodada gerou dois blocos, e o segundo mistura leis inteiras e divididas, por isso o tempo não é separado por etapa.

## Rodada LC 95 com janela de 24.576 tokens (j24k)

Em 12/11/2026, os três modelos rodaram de novo as 376 leis da amostra, todos com a mesma configuração: janela de 24.576 tokens e teto de 4 × o trecho. Cada um rodou com e sem espaço livre no JSON, teve uma nova tentativa das falhas e uma junção. A GPU foi uma RTX PRO 6000 Blackwell (96 GB). Leis com JSON válido na junção: Qwen 376, Gemma 368 e Llama 373. Os detalhes, a origem de cada resposta e as leis que falharam estão em [resultados/lc95/README.md](resultados/lc95/README.md).

## Tempo e custo

A A100 consome cerca de 5,3 unidades de computação do Colab por hora. Um pacote de 100 unidades custou R$ 58,00, ou R$ 0,58 por unidade.

| Modelo | Leis inteiras | Leis divididas | Total | Unidades | Custo |
|---|---|---|---|---|---|
| Qwen 2.5 7B | 1 h 09 min | 1 h 05 min | 2 h 14 min | 11,8 | R$ 6,87 |
| Gemma 3 12B | 5 h 54 min | 4 h 55 min | 10 h 49 min | 57,3 | R$ 33,24 |
| Llama 3.1 8B | 2 h 32 min | 3 h 18 min | 5 h 50 min | 30,9 | R$ 17,95 |
| Rodadas livres e teste da gramática | | | 15 min | 1,4 | R$ 0,79 |
| **Total** | | | **19 h 09 min** | **101,5** | **R$ 58,85** |

Esses valores são estimativas a partir do tempo de geração impresso pelos notebooks. O consumo real foi maior: não entram aí a carga do modelo a cada sessão, a gravação no Drive nem as sessões que ficaram paradas.

## Previsão para as leis que faltam

As leis acima de 9.000 tokens são cerca de 4% do acervo, mas reúnem 54% dos dispositivos. A projeção usa a velocidade medida nas leis divididas e é grosseira, porque essas leis são muito maiores que as já processadas.

| Modelo | Leis | Tempo de A100 | Unidades | Custo |
|---|---|---|---|---|
| Qwen 2.5 7B | 662 | 3 h 04 min | 16 | R$ 9,45 |
| Gemma 3 12B | 584 | 12 h 51 min | 68 | R$ 39,49 |
| Llama 3.1 8B | 645 | 9 h 12 min | 49 | R$ 28,30 |
| **Total** | | **25 h 08 min** | **133** | **R$ 77,25** |

A recomendação do relatório é rodar só o Qwen: é o melhor nas leis médias, quase não cai em laço e é o mais barato.

## O que há nesta pasta

| Arquivo ou pasta | Papel |
|---|---|
| `notebooks/` | Um notebook do Colab por modelo (`qwen_a100.ipynb`, `gemma_a100.ipynb`, `llama_a100.ipynb`). Os três têm o mesmo programa; muda o modelo. |
| `prompt.py` | O texto do prompt, os dois exemplos e os avisos usados nos trechos. |
| `entrada.py` | Recorte do HTML e divisão da lei em trechos. |
| `resposta.py` | Lê a resposta do modelo, repara a que foi cortada, emenda os trechos e converte para o formato do regex. |
| `comparar.py` | Calcula as medidas contra o regex e grava as tabelas em `comparacao/`. |
| `analise.py` | Parte das tabelas de `comparar.py` e grava, em `analise/`, as tabelas por tamanho, por época, de respostas cortadas, de custo e a previsão das leis que faltam. |
| `resultados/acervo/` | As rodadas restritas dos três modelos, as tabelas (`comparacao/` e `analise/`) e os tempos de geração (`tempos.csv`). É a base dos números acima. |
| `resultados/amostra/` | As rodadas em modo livre, sobre a amostra de 300 leis. |
| `resultados/testes/` | Os testes na T4 e o teste da gramática sem espaço livre. |
| `resultados/lc95/` | As rodadas restritas com o prompt da LC 95/1998, sobre as 376 leis da amostra da avaliação. |
| `relatorios/` | O relatório técnico atual e, em `anteriores/`, os dois que vieram antes. |
| `../tests/test_modelos.py` | Testes do recorte, da divisão, da resposta e da comparação, sem GPU. |

O prompt e as funções de recorte e divisão estão repetidos dentro dos notebooks, que precisam rodar sozinhos no Colab. Uma mudança em `prompt.py` ou `entrada.py` tem de ser copiada para eles. O teste `test_notebooks_trazem_o_mesmo_prompt_e_esquema` falha quando o prompt ou o esquema dos notebooks diverge de `prompt.py`.

### Dentro de cada notebook

| Célula | O que faz |
|---|---|
| Configuração | Modelo, nome da rodada (`NOME`, que dá o nome da pasta no Drive), modo (`RESTRITA`), leis a processar (`AMOSTRA` ou `LIMITE`) e parâmetros: `MAX_TOKENS_LEI`, `TRECHO`, `JANELA`, `BLOCO`. |
| Preparação | Monta o Drive, clona o repositório e instala `vllm` e `lxml`. |
| Prompt | Grava o texto do prompt. |
| Programa | Grava `fragmentar.py`: recorta, divide, monta os pedidos, gera e grava as respostas. |
| Execução | Roda o programa. O que já foi respondido é pulado, então a rodada pode ser retomada. |
| Conferência | Conta respostas, JSON válidos e cortadas, e compara o número de artigos com o do regex. |
| Pacote | Junta as respostas novas num zip, para baixar do Drive de uma vez. |

### Dentro de cada rodada

| Arquivo | Conteúdo |
|---|---|
| `bruto/<ano>/<lei>.txt` | A resposta do modelo como veio. |
| `json/<ano>/<lei>.json` | A mesma resposta, quando é um JSON válido. |
| `registro.csv` | Uma linha por lei: tokens gerados, se foi cortada, se é válida e, nas divididas, quantos trechos. |
| `longas.txt` | As leis que ficaram de fora por passarem do limite de tokens. |

As pastas `bruto/` e `json/` somam cerca de 30 mil arquivos por rodada do acervo e também estão no repositório.

## Como rodar

**Gerar as respostas** (Colab, GPU A100):

1. Envie ao Colab o notebook do modelo, que está em `notebooks/`.
2. Na primeira célula, ajuste:
   - `NOME`: o prefixo da pasta da rodada no Drive (hoje `<modelo>_lc95`). A pasta é `fragmentos_leis/<NOME>_restrita` (ou `_livre`). **A lei que já tem resposta nessa pasta é pulada**, então uma rodada com outro prompt precisa de outro `NOME`, ou as respostas antigas são aproveitadas no lugar de novas.
   - `AMOSTRA`: o CSV com a coluna `slug` das leis a processar (hoje, as 376 leis de `avaliacao/amostra/amostra_leis.csv`). O programa para com erro se alguma não estiver na coleta. Com `AMOSTRA = None`, vale `LIMITE`: um número N sorteia N leis fixas do acervo, e `None` processa tudo o que falta.
   - `RESTRITA`: `True` para a decodificação restrita ao esquema (mede o conteúdo), `False` para o modo livre (mede quantas respostas saem como JSON válido).
   - `MAX_TOKENS_LEI`: `9000`, ou `None` para incluir as leis restantes.
3. Execute todas as células. Gemma e Llama exigem o token do Hugging Face nos **Secrets** do Colab, com o nome `HF_TOKEN`. Ao fim, baixe o zip criado pela célula **Pacote** (`<pasta da rodada>_novas.zip`) e extraia no grupo de `resultados/` da rodada, juntando à pasta dela. Confira as contagens contra o `registro.csv`.
4. Desconecte o ambiente, para não gastar unidades com a GPU parada.

**Comparar com o regex** (máquina local, a partir da raiz do projeto):

```
python -m modelos.comparar
python -m modelos.comparar --resultados modelos/resultados/amostra
python -m modelos.comparar --resultados modelos/resultados/lc95
```

O primeiro comando compara as rodadas de `resultados/acervo/`; as tabelas saem em `comparacao/`, dentro do grupo comparado. A comparação do acervo leva cerca de 15 minutos.

**Tabelas por tamanho, época, cortes e custo** (depois da comparação):

```
python -m modelos.analise
```

As tabelas saem em `resultados/acervo/analise/`. O tempo de geração não fica gravado nas respostas: ao fim de cada rodada, some os segundos impressos pelo notebook e acrescente uma linha a `resultados/acervo/tempos.csv` (rodada, etapa `inteiras` ou `divididas`, segundos, observação). É desse arquivo que saem as unidades e o custo.

**Testes:**

```
python -m unittest tests.test_modelos
```
