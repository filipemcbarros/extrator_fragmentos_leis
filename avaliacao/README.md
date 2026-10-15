# Avaliação dos métodos de fragmentação (dataset ouro)

Material para montar o dataset ouro e comparar os três LLMs (Qwen, Gemma e Llama) com o regex.

## Amostra

- População: 15.754 leis com até 9.000 tokens, respondidas pelos três modelos.
- Tamanho pela fórmula de Cochran, com 5% de erro e 95% de confiança (p = 0,5) e correção para população finita: **376 leis**.
- Estratificada por época (1891-1945, 1946-1988, 1989-2026) e por tamanho (tercis do nº de dispositivos do regex), 9 estratos com alocação proporcional. Cada lei tem peso N_h / n_h (coluna `peso`).
- Semente 2026, para o sorteio ser reprodutível com `montar_amostra.py`.

## Divisão da anotação

As 376 leis foram divididas em três pastas, uma por anotador (`Paulo/`, `Pedro/`, `Filipe/`), cada uma com a planilha `anotacao_<nome>.xlsx` e o HTML das leis em `leis/`. Cada lei é anotada por uma só pessoa (sem dupla anotação).

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

**Atenção:** o mini-ouro do piloto (`piloto/`) foi feito pelo Claude, não por um anotador humano. É provisório e serve só para testar a métrica; não deve entrar nos resultados.
