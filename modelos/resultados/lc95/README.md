# Rodadas com o prompt da LC 95/1998

Respostas dos três modelos, em modo restrito, sobre as 376 leis da amostra da avaliação (`avaliacao/amostra/amostra_leis.csv`). O resumo das duas primeiras rodadas está em [../../README.md](../../README.md).

| Rodada | Pastas | Quando | GPU |
|---|---|---|---|
| Original | `<modelo>_lc95_restrita` | 07/11/2026 | A100 40 GB |
| Segunda tentativa das cortadas | `<modelo>_lc95_restrita_refeitas` | 10/11/2026 | A100 40 GB |
| Janela de 24.576 tokens (**j24k**) | `<modelo>_lc95_j24k_restrita*` | 12/11/2026 | RTX PRO 6000 Blackwell 96 GB (G4 do Colab) |

`<modelo>` é `qwen`, `gemma12b` ou `llama`.

## Rodada j24k

Uma configuração única para as 376 leis e os três modelos, sem nenhuma lei de fora. Os parâmetros são os dos notebooks em `modelos/notebooks/`:

- janela de 24.576 tokens e teto da resposta em 4 × o trecho;
- leis acima de 3.000 tokens divididas em trechos;
- `MAX_TOKENS_LEI = None`;
- temperatura 0, precisão cheia.

Cada modelo passa por estas etapas, cada uma com a sua pasta:

| Pasta | O que é |
|---|---|
| `_j24k_restrita` | As 376 leis, com espaço em branco livre no JSON. |
| `_j24k_restrita_sem_espacos` | As 376 leis de novo, sem espaço livre (`SEM_ESPACOS`). |
| `_j24k_restrita_nova_tentativa` | Só as leis sem JSON válido nas duas rodadas acima, em lote pequeno. |
| `_j24k_restrita_nova_tentativa_sem_espacos` | As que ainda falharam, sem espaço livre. Só existe quando sobrou alguma. |
| `_j24k_restrita_junta` | Para cada lei, a primeira resposta válida nesta ordem: com espaço, sem espaço, nova tentativa com espaço, nova tentativa sem espaço. A última coluna do `registro.csv` diz de onde veio. |

**A pasta para a avaliação é a `_junta`.** As outras ficam para a rastreabilidade.

### Contagens

Leis com JSON válido, contadas no `registro.csv` de cada pasta:

| Pasta | Qwen | Gemma | Llama |
|---|---|---|---|
| Com espaço livre | 369 (7 cortadas) | 357 (19 cortadas) | 323 (53 cortadas) |
| Sem espaço livre | 374 (2 cortadas) | 367 (9 cortadas) | 371 (5 cortadas) |
| Nova tentativa (leis / válidas) | 1 / 1 | 8 / 0, e 8 / 0 sem espaço | 5 / 0, e 5 / 2 sem espaço |
| **Junção** | **376** | **368** | **373** |
| Divididas em trechos | 28 | 25 | 28 |

Origem das respostas na junção:

| Origem | Qwen | Gemma | Llama |
|---|---|---|---|
| Com espaço livre | 369 | 365 | 326 |
| Sem espaço livre | 6 | 11 | 48 |
| Nova tentativa, com espaço | 1 | 0 | 0 |
| Nova tentativa, sem espaço | 0 | 0 | 2 |

Na junção do Gemma, as 8 leis sem válida aparecem com origem "com espaço livre". É a resposta da primeira rodada, que fica quando nenhuma rodada deu certo.

Leis sem JSON válido na junção:

- **Gemma (8):** `lei-4887-9-dezembro-1965-368418`, `lei-5054-29-junho-1966-368478`, `lei-6075-10-julho-1974-357556`, `lei-6272-28-novembro-1975-357244`, `lei-7028-13-setembro-1982-357310`, `lei-7283-11-dezembro-1984-356964`, `lei-7358-2-setembro-1985-356975` e `lei-11518-5-setembro-2007-559260`. Nas sete primeiras, o modelo entra em laço de estrutura: aninha `titulo` (ou `disposicoes`) vazio dentro de outro, até o limite. Na 11518, um dos 3 trechos foi cortado.
- **Llama (3):** `lei-14034-5-agosto-2020-790505`, `lei-2877-20-setembro-1956-355156` e `lei-5500-20-setembro-1968-358573`.

### Cuidados na análise

- **Na rodada com espaço livre, as contagens repetem as da A100.** Qwen 369 válidas e 7 cortadas; Llama 323 e 53. A troca de GPU não mudou esses números. As respostas em si não foram comparadas uma a uma.
- **A junção escolhe, para cada lei, a primeira resposta válida.** O procedimento é o mesmo nos três modelos, mas a origem precisa ser relatada junto com as métricas.
- **A gramática sem espaço livre deixa o JSON válido, mas não necessariamente o conteúdo.** No acervo, ela piorou a concordância do Llama. Na junção do Llama, 50 das 376 respostas vêm dela.
- **A nova tentativa depende da composição do lote.** Com temperatura 0, a mesma lei dá a mesma resposta no mesmo lote, mas pode mudar num lote diferente. Por isso, é difícil de reproduzir.
- **Os tempos de geração desta rodada não foram anotados,** e `tempos.csv` não foi atualizado.

### Comparar com o regex

A partir da raiz do projeto, só sobre as junções:

```
python -m modelos.comparar --resultados modelos/resultados/lc95 --rodadas "*_j24k_restrita_junta"
```

As tabelas saem em `modelos/resultados/lc95/comparacao/`.
