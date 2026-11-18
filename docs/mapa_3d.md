# Laboratório: mapa eleitoral 3D

A camada experimental fica em `pages/01_Mapa_3D.py` e usa
`mapa_eleicoes/electoral_3d.py`. Não altera `app.py`, o Atlas
Folium, as páginas Deltas/Viradas, nem os seletores atuais.

## Executar (Makefile é o único ponto de entrada)

- `make bootstrap`: instalar dependências com uv.
- `make preview-3d ANO=2026`: abrir somente a página 3D com os Parquets já existentes (sem baixar nem reprocessar os dados).
- `make run-3d ANO=2026`: preparar tudo via `app-ready` existente, e iniciar o laboratório 3D.
- `make test-3d`: testar somente a camada nova.
- `make test`: executar a suíte completa.

## Fontes e regras

A fonte exclusiva dos votos é `data/serving/ANO/votos_*.parquet`.
O pipeline reutiliza `combine_sources` para eliminar sobreposições
BR/UF e `region_results` para calcular 1º, 2º e diferença.
Denominador de percentuais: votos válidos (nominais + legenda),
sem votos brancos e nulos.

A correspondência espacial usa apenas `UF + código TSE -> código IBGE`
(`data/reference/tse_ibge.csv`) e a malha de municípios oficial
(`data/geo/municipios.geojson`). Não há junção por nome.
As barras usam `representative_point()`, que situa o ponto **dentro**
do município. Esses pontos **não** representam locais de votação,
centroides de zona ou limites eleitorais.

O plano de fundo exibe apenas divisas estaduais derivadas da malha municipal.
Cor por número eleitoral: 13 vermelho, 22 azul, demais cores estáveis;
empates cinza. No modo votos de candidato a cor indica o selecionado.

Métricas: margem absoluta, margem em pontos percentuais, votos
do vencedor e votos do candidato selecionado. A altura usa a transformação
`H * sqrt(min(valor / P99, 1))`, onde P99 é a referência positiva do
recorte. **Não é escala linear nem altitude real**. Tooltip mostra
os votos/margens reais. Zero é zero e ausência de geografia não inventa
uma posição.

## Estado e limitações da PoC

Filtros de eleição, UF, cargo, turno, município e candidato; pan/zoom,
inclinação, rotação e hover via PyDeck/deck.gl. A seleção de município
é feita no controle lateral, sem eventos que reiniciem a câmera durante
a navegação. Drill-down por clique, zonas eleitorais aproximadas,
animação entre pleitos e otimização visual mais fina ficam para análise
posterior.

Cobertura = apenas arquivos oficiais efetivamente presentes nos dados locais.
Não se presumem resultados de turnos ausentes, cobertura de todas as UFs
nem totalização completa.

Desenvolvimento isolado em `feature/electoral-3d-map-20261112`, sem
integração ou merge em `dev`/`main` antes de avaliação.
