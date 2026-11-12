# Métricas: ouro × regex × LLMs

Esta pasta mede qual método de fragmentação chega mais perto do dataset ouro. Os quatro métodos comparados são o regex, o Qwen, o Gemma e o Llama.

## Passo 1: o que é comparado

| Fonte | Onde fica | Leis |
|---|---|---|
| **Ouro** (referência) | `avaliacao/ouro_final/ouro_lc95.json` | 376 leis, 3.508 dispositivos |
| Regex | `coleta/<ano>/json/<slug>.json` | 376 |
| Qwen | `modelos/resultados/lc95/qwen_lc95_j24k_restrita_junta/` | 376 com JSON válido |
| Gemma | `modelos/resultados/lc95/gemma12b_lc95_j24k_restrita_junta/` | 368 com JSON válido |
| Llama | `modelos/resultados/lc95/llama_lc95_j24k_restrita_junta/` | 373 com JSON válido |

As 376 leis são as da amostra estratificada (`avaliacao/amostra/amostra_leis.csv`). Ela tem 9 estratos (época × tamanho), e a coluna `peso` de cada lei vale N_h / n_h.

As cinco fontes passam pela mesma função, `modelos.resposta.normalizar`. Essa função emenda os trechos das leis que foram divididas e dá a cada dispositivo um caminho no mesmo padrão, por exemplo `CAPITULO I, Art. 2º, § 1º, a)`.

## Passo 2: casar os dispositivos

Cada dispositivo do ouro procura o seu par no método. Os casamentos são dois.

**Estrito (a métrica principal).** O par é procurado pelo caminho sem os agrupadores, por exemplo `Art. 2º, § 1º, a)`. Tirar os agrupadores evita que um capítulo esquecido derrube todos os artigos de dentro dele. Os agrupadores (capítulo, seção...) casam pelo próprio caminho. Quando o mesmo caminho se repete na lei, o casamento segue a ordem. Esse casamento cobra o texto e também a posição na árvore.

**Flexível (colunas `_flex`).** Depois do estrito, o dispositivo do ouro que ficou sem par recebe, entre os que sobraram no método, o de texto mais parecido. O par só vale se a similaridade for de pelo menos 0,5, e a escolha é gulosa, do par mais parecido para o menos. Esse casamento mede só o texto. A diferença entre o estrito e o flexível mostra o quanto o método perde por errar a hierarquia ou o tipo, como marcar um inciso como item ou pendurar um parágrafo no artigo errado.

Três casos contam como erro, nos dois casamentos:

- **Faltando**: o dispositivo do ouro ficou sem par. Ele conta como similaridade 0 e erro.
- **Sobrando**: o método inventou ou duplicou um dispositivo. Ele entra como 0 e erro no denominador da lei.
- **Lei sem JSON válido**: todos os dispositivos dela contam como 0.

## Passo 3: as duas métricas por dispositivo

- **Similaridade** é a Levenshtein normalizada, `1 - distância de edição / tamanho do maior texto`. Vai de 0 a 1, e 1 é o texto idêntico. O texto comparado é a rubrica mais o texto, com os espaços colapsados e `°` trocado por `º`. Maiúsculas, acentos e pontuação contam.
- **Acerto** vale 1 quando a similaridade é ≥ 0,95. A **acurácia** é a fração de acertos.

## Passo 4: do dispositivo para a nota global

1. **Por lei.** Somam-se as similaridades (ou os acertos) e divide-se o total por (dispositivos do ouro + sobras). Assim, cada lei ganha uma nota de similaridade e uma de acurácia para cada método.
2. **Para a população.** As notas das leis viram a estimativa estratificada para as 15.754 leis, `Σ W_h · média do estrato h`, com `W_h = N_h / N`. O IC de 95% usa a variância da amostragem estratificada, com correção de população finita.
3. **Comparação entre os métodos.**
   - A diferença lei a lei (pareada) entre dois métodos é estimada da mesma forma, com IC de 95%.
   - O **teste de Friedman** verifica se os 4 métodos diferem.
   - O **Wilcoxon pareado** com **correção de Holm** diz quais pares diferem.
   - Os dois testes usam as 376 leis sem peso.

Como conferência, a tabela de resumo também traz a média **por dispositivo** (`_por_dispositivo`). Ela soma todos os dispositivos e pondera cada um pelo peso da sua lei. Nessa média, as leis grandes pesam mais.

## Passo 5: rodar

Da raiz do repositório:

```bash
pip install pandas rapidfuzz scipy xlsxwriter
python -m metricas.metricas_ouro
```

Também dá para abrir `metricas/comparacao_ouro.ipynb` no Jupyter, no VS Code ou no Colab (com o repositório clonado) e rodar todas as células. O notebook faz o mesmo passo a passo e mostra cada tabela:

1. lê as fontes e conta as leis com JSON válido;
2. compara dispositivo a dispositivo;
3. mostra o resultado global com os ICs;
4. roda o Friedman e o Wilcoxon-Holm;
5. faz os recortes por época, tamanho e tipo de dispositivo;
6. compara os campos da lei (epígrafe, ementa, preâmbulo e fecho);
7. grava a planilha e os CSVs em `metricas/resultados/`.

A rodada leva poucos segundos.

## Passo 6: ler o Excel (`resultados/comparacao_ouro.xlsx`)

| Aba | O que tem |
|---|---|
| `sobre` | As regras acima, em resumo. |
| `resumo` | Uma linha por método: posição, similaridade e acurácia (estrita e flexível) com IC de 95%, médias por dispositivo e totais de faltando, sobrando e acertos. |
| `friedman` | O teste de Friedman para cada métrica. |
| `pares` | Cada par de métodos: a diferença com IC, em quantas leis cada um foi melhor, o p do Wilcoxon e o p ajustado por Holm. |
| `por_epoca`, `por_tamanho`, `por_estrato` | As quatro métricas por grupo e por método. |
| `por_tipo` | Por tipo de dispositivo (artigo, parágrafo, inciso...): quantos são, a similaridade, a acurácia e quantos faltaram. |
| `campos_resumo`, `campos` | A similaridade da epígrafe, da ementa, do preâmbulo e do fecho, que fica fora da nota global. |
| `por_lei` | Uma linha por lei e método, com as notas e as contagens. |
| `dispositivos` | **Uma linha por dispositivo do ouro** (veja abaixo). |
| `sobras` | Os dispositivos que o método trouxe e que não estão no ouro, com a indicação de se casaram depois pelo texto. |

Na aba `dispositivos`, as colunas são:

- `slug`, `ano`, `epoca`, `tamanho`, `estrato`, `peso`, `anotador`, `ordem`, `tipo`, `caminho` e `texto_ouro`;
- para cada método (`regex`, `qwen`, `gemma`, `llama`):
  - `caminho_<m>` e `texto_<m>`: o que o método deu;
  - `casado_por_<m>`: `caminho` (estrito), `texto` (só no flexível) ou `faltando`;
  - `sim_<m>` e `acerto_<m>`: o casamento estrito;
  - `sim_flex_<m>` e `acerto_flex_<m>`: o casamento flexível.

Os filtros do Excel ajudam a achar os erros, por exemplo `acerto_llama = 0` ou `casado_por_qwen = texto`.

## Resultado (rodada j24k, 12/11/2026)

Estimativa para a população, com IC de 95%:

| Método | Similaridade | Acurácia | Similaridade flex | Acurácia flex | Faltando | Sobrando |
|---|---|---|---|---|---|---|
| Regex | 0,967 (0,952–0,982) | 0,964 (0,949–0,980) | 0,984 | 0,981 | 93 | 106 |
| Gemma | 0,801 (0,770–0,832) | 0,792 (0,760–0,823) | 0,847 | 0,836 | 726 | 1.514 |
| Qwen | 0,742 (0,716–0,769) | 0,727 (0,699–0,755) | 0,832 | 0,816 | 1.066 | 1.411 |
| Llama | 0,522 (0,484–0,559) | 0,511 (0,474–0,549) | 0,804 | 0,788 | 1.927 | 3.010 |

- **Estrito:** o Friedman dá p < 10⁻⁸⁰, e todos os pares diferem no Wilcoxon-Holm (p < 0,05). A ordem é Regex > Gemma > Qwen > Llama.
- **Flexível:** Gemma e Qwen empatam (p ≈ 0,09), e os dois ficam acima do Llama.
- A maior parte da perda dos LLMs vem da **hierarquia**, não do texto. No Llama, a similaridade sobe de 0,52 para 0,80 quando a posição na árvore deixa de ser cobrada. Nos parágrafos do Qwen, a acurácia é de 28% no estrito e de 77% no flexível.

## Limitações

- **Viés a favor do regex.** O ouro foi corrigido a partir do rascunho do regex (`avaliacao/amostra/ouro_rascunho.csv`). Onde os anotadores não mexeram, o regex coincide com o ouro por construção.
- **Sem dupla anotação.** Cada lei foi anotada por uma pessoa e revisada por outra, e por isso não há medida de concordância entre anotadores.
- **O limiar de 0,95 e o mínimo de 0,5** do casamento flexível são escolhas nossas. Os dois ficam no topo de `metricas_ouro.py` (`LIMIAR` e `MINIMO_TEXTO`) e podem ser mudados.
- **Os testes não usam peso.** O Friedman e o Wilcoxon tratam as 376 leis como iguais. As estimativas e os ICs usam os pesos dos estratos.

## Arquivos

| Arquivo | O que é |
|---|---|
| `metricas_ouro.py` | Leitura das fontes, casamento, métricas, estatística e gravação. |
| `comparacao_ouro.ipynb` | O notebook passo a passo, já rodado, com as tabelas. |
| `resultados/comparacao_ouro.xlsx` | A planilha descrita no Passo 6. |
| `resultados/resumo.csv`, `pares.csv`, `por_lei.csv` | As mesmas tabelas em CSV. |
