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
3. **Geração.** O modelo devolve um JSON com `titulo`, `ementa`, `preambulo`, `fecho` e a árvore de `dispositivos`.
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
| `relatorios/` | O relatório técnico atual e, em `anteriores/`, os dois que vieram antes. |
| `../tests/test_modelos.py` | Testes do recorte, da divisão, da resposta e da comparação, sem GPU. |

O prompt e as funções de recorte e divisão estão repetidos dentro dos notebooks, que precisam rodar sozinhos no Colab. Uma mudança em `prompt.py` ou `entrada.py` tem de ser copiada para eles.

### Dentro de cada notebook

| Célula | O que faz |
|---|---|
| Configuração | Modelo, pasta de saída e parâmetros: `LIMITE`, `MAX_TOKENS_LEI`, `TRECHO`, `JANELA`, `BLOCO`. |
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
2. Na primeira célula, ajuste `LIMITE` (`300` para a amostra, `None` para tudo o que falta) e `MAX_TOKENS_LEI` (`9000`, ou `None` para incluir as leis restantes).
3. Execute todas as células. Ao fim, baixe o zip criado pela célula **Pacote** e extraia em `resultados/acervo/`, juntando à pasta da rodada.
4. Desconecte o ambiente, para não gastar unidades com a GPU parada.

**Comparar com o regex** (máquina local, a partir da raiz do projeto):

```
python -m modelos.comparar
python -m modelos.comparar --resultados modelos/resultados/amostra
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
