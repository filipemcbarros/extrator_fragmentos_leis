# fragmentos_leis

Lê a página HTML de uma lei, extrai os seus dispositivos — artigo, parágrafo,
inciso, alínea, item — e os devolve hierarquizados.

A referência de origem é o acervo [Legin](https://www2.camara.leg.br/legin) da
Câmara dos Deputados, mas o extrator tem um caminho genérico para páginas de
outra procedência.

## Instalação

```bash
pip install -r requirements.txt
```

Dependências: `requests` (baixar a página) e `lxml` (percorrer o HTML). Os testes
usam apenas a biblioteca padrão.

## Uso

Pela linha de comando:

```bash
# resumo das estruturas encontradas
python -m fragmentador https://www2.camara.leg.br/legin/fed/lei/2021/lei-14133-1-abril-2021-791222-publicacaooriginal-162591-pl.html

# árvore completa
python -m fragmentador exemplos/lei-14133-2021.html --arvore

# só os artigos, um por linha, com o caminho hierárquico
python -m fragmentador exemplos/lei-14133-2021.html --tipo artigo

# exporta tudo em JSON
python -m fragmentador exemplos/lei-14133-2021.html --json lei.json
```

Como biblioteca:

```python
from fragmentador import fragmentar_referencia, Tipo

lei = fragmentar_referencia("exemplos/lei-14133-2021.html")

print(lei.titulo)        # LEI Nº 14.133, DE 1º DE ABRIL DE 2021
print(lei.contagem())    # {'alinea': 151, 'artigo': 194, 'capitulo': 32, ...}

for alinea in lei.por_tipo(Tipo.ALINEA):
    print(alinea.caminho(), "->", alinea.texto)
    # TITULO I, CAPITULO I, Art. 1º, § 3º, II, a) -> sejam exigidas para a obtenção...
```

## Coleta em lote por ano

Percorre a [busca de legislação da Câmara](https://www.camara.leg.br/legislacao/busca),
abre cada norma, segue o link "Texto - Publicação Original" e fragmenta o texto:

```bash
python -m fragmentador.coleta --ano 2026            # todas as leis ordinárias de 2026
python -m fragmentador.coleta --ano 2026 --limite 5 # só as 5 primeiras, para testar
```

O resultado fica isolado em `coleta/<ano>/`, versionado junto com o código:

```
coleta/2026/
  json/<slug>.json   uma lei fragmentada por arquivo, com o campo "norma" apontando a página de origem
  html/<slug>.html   a publicação original baixada, para refragmentar sem voltar à rede
  indice.json        desfecho de cada lei: arquivo gerado, contagem de estruturas ou erro
```

Uma nova execução reaproveita o HTML já baixado e só busca na rede o que falta;
`--forcar` baixa tudo de novo. A pausa entre pedidos é de 1 s (`--pausa`).

A busca é ordenada por data: a ordenação padrão, por relevância, não é estável
entre páginas e chegou a omitir 12 das 206 leis de 2026. Leis sem publicação
original no acervo (há as que só trazem retificação parcial) ficam no índice com
erro e a lista dos textos disponíveis.

## A hierarquia

Segue a articulação da Lei Complementar 95/1998. A unidade básica é o artigo; o
artigo desdobra-se em parágrafos e incisos; o inciso, em alíneas; a alínea, em
itens. Acima do artigo ficam os agrupadores, que organizam sem comandar.

```
PARTE > LIVRO > TÍTULO > CAPÍTULO > SEÇÃO > SUBSEÇÃO
        └─ ARTIGO
             ├─ PARÁGRAFO ─┐
             └─ INCISO  ───┴─ (o inciso pende do artigo ou do parágrafo)
                  └─ ALÍNEA
                       └─ ITEM
```

O encaixe é decidido por uma pilha e pelo nível de cada tipo, e não pelo
fragmento anterior. É o que reproduz, sem exceção codificada, o caso em que o
mesmo tipo pende de pais diferentes: o inciso que vem logo após o caput é filho
do artigo; o que vem depois de um parágrafo é filho do parágrafo. Na Lei
14.133/2021 isso dá 414 incisos sob artigo e 223 sob parágrafo.

## Decisões que o texto real impôs

**Citação de alteração.** A lei que altera outra transcreve o texto alterado
entre aspas. Sem tratamento, a Lei 14.133/2021 "ganharia" os arts. 337-E a 337-P
do Código Penal, que ela apenas insere. O fragmentador detecta o bloco citado e
o mantém como texto do artigo que promove a alteração.

**Fonte que cola o rótulo.** No acervo há linhas em que a citação termina e o
artigo seguinte começa sem quebra: `.......... " (NR) Art. 178. O Título...`.
Como o reconhecedor só vê o início da linha, esses artigos se perderiam; por isso
a linha é separada antes da análise.

**Citação sem fechamento.** Nem todo bloco citado fecha as aspas. Quando isso
acontece, o bloco é encerrado ao aparecer o artigo que continua a numeração da
lei hospedeira — o artigo acrescentado por alteração nunca continua essa
sequência.

**Inciso exige travessão.** `III -` é inciso; uma linha que começa por `I` ou `V`
sem travessão é texto corrido. Da mesma forma, `1.` só é item quando há alínea
aberta; fora disso é numeração dentro do próprio texto.

**Fidelidade à fonte.** O texto não é corrigido. A Lei 5.603/1970 traz
"Denominar-se-à" no acervo, com crase, e assim é devolvida.

## Conferência

Os números abaixo saem dos testes, sobre as páginas reais guardadas em
`exemplos/`:

| Lei | Artigos | Parágrafos | Incisos | Alíneas | Agrupadores |
|---|---|---|---|---|---|
| 5.603/1970 | 3 | — | — | — | — |
| 8.666/1993 | 125 | 230 | 274 | 55 | 6 capítulos, 19 seções |
| 14.133/2021 | 194 | 403 | 637 | 151 | 5 títulos, 32 capítulos, 13 seções, 5 subseções |

A Lei 14.133/2021 fecha a sequência de 1 a 194 sem lacuna e sem artigo intruso —
é o teste mais exigente, porque ela altera o Código Penal e outras três leis. A
publicação original da 8.666/1993 termina no art. 125; o art. 126 veio depois,
por alteração.

```bash
python -m unittest discover -s tests -v
```

## Estrutura

```
fragmentador/
  modelos.py      Fragmento, Lei, tipos e níveis da hierarquia
  rotulos.py      reconhecimento dos rótulos que abrem cada dispositivo
  extracao.py     HTML -> linhas de texto (Legin e genérico)
  fragmentador.py linhas -> árvore de dispositivos
  fonte.py        obtenção do HTML, por URL ou arquivo
  coleta.py       coleta em lote: busca da Câmara -> JSON por lei
  cli.py          linha de comando
tests/            suíte em unittest, sem dependências
exemplos/         páginas reais usadas na conferência
```

## Limites conhecidos

- O extrator genérico, para páginas fora do padrão Legin, escolhe o maior bloco
  de texto da página. Funciona em página de lei, onde o corpo normativo domina;
  não foi exercitado em portais com outra diagramação.
- Não há tratamento de texto compilado com marcas de vigência ("Revogado pela Lei
  nº ..."), que hoje permanecem no texto do dispositivo.
- O item (`1.`, `2.`) só é reconhecido sob alínea. Leis que numeram itens sob
  inciso, prática minoritária, não terão esse nível separado.
```
