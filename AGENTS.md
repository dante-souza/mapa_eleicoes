# Instruções para agentes — mapa_eleicoes

1. **Makefile é o único ponto de entrada**: instalar, rodar app, baixar/importar, processar e testar sempre por `make <target>`. Nunca instrua o operador a invocar `python`, `uv`, `pip` ou `streamlit` diretamente para tarefas do projeto.
2. Dependências: `make bootstrap` cria ambiente virtual, usa `pip install uv` no venv e em seguida `uv pip install -r requirements.txt`.
3. Fonte de verdade: arquivos CSV/ZIP oficiais do TSE. Conservar ZIP de origem, documento e data da extração, não inventar dados nem afirmar cobertura nacional com amostra parcial.
4. Dados em `data/raw`, `data/processed`, `data/geo`, `data/reference` não são versionados. O repositório guarda códigos, testes, modelos, documentação, manifests de formato (sem dados brutos).
5. Não confundir `município` e `zona`: limite de município nunca deve ser representado como polígono de zona sem metadados geoespaciais próprios. Cruzamentos só por identificadores oficiais TSE/IBGE, nunca por nome.
6. Cada linha de votação por seção traz o número de votos de um votável/cargo/seção. Para brancos, nulos, abstenções e totais de comparecimento, respeitar a semântica de cada tabela e impedir dupla contagem entre cargos.
7. Fluxo Git: trabalhar em branch isolada, abrir PR de revisão; não alterar diretamente a `main` e não efetuar merge sem aprovação humana. Não modificar CI sem aprovação.
8. Testes padrão: `make test` e `make validate`. `make test-offline`/`make ingest-offline` são apenas diagnósticos no sandbox sem rede, não substituem a instalação real por `uv`.
9. **Motor tabular: Polars.** Nunca introduzir `import pandas` em pipeline, mapa ou testes. GeoPandas (dependencia interna de pandas) e exclusivamente geoespacial.
10. **Fronteira Polars / GeoPandas:** nao usar `to_pandas()`, `GeoDataFrame.merge(Polars)` ou Arrow dtypes implicitamente. Converter apenas valores finais para registros Python via `geo_bridge.add_properties`. Testar codigo IBGE com zeros, Int64 de votos e serializacao GeoJSON.
