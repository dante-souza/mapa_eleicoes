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

11. **`make run` e ponta a ponta.** Antes de iniciar a interface, executa `make prepare-data`: detecta ZIPs de `data/`, `data/incoming/` ou `data/raw/ANO/`, extrai bundles verificados, agrega arquivos `votacao_secao`, trata `munzona` como datasets independentes em Parquet e valida os votos. Nunca somar o mesmo voto a partir de fontes distintas.
12. **Resiliência/reprodutibilidade:** nao sobrescrever brutos distintos, guardar SHA-256 e tamanho no manifesto, cachear resultados por origem e versao do pipeline; falhas impedem entrada no dashboard. Bundle gerado por `make data-pack` usa ZIP64 e manifesto; ZIP grande e outros artefatos de dados permanecem fora do Git.
13. **Geografia nao e automaticamente fabricada:** crosswalk TSE/IBGE e malhas precisam de insumos oficiais separados; faltando geometrias, mostrar ausencia no mapa.

14. **Malha oficial:** `make geo-setup` e `make geo-check` sao os alvos para configurar IBGE 2025 e correspondencia TSE/IBGE, preservando originais, hashes e datas. Nunca usar join por nome; municipio nao e zona eleitoral.
15. **Preview com cobertura incompleta:** `make preview` apenas abre dados ja processados, sem afirmar cobertura completa e sem esconder falhas do `make run`. Nao altere a exigencia de integridade do preparo dos brutos.
16. **GeoPandas e Polars isolados:** geometrias no GeoPandas, tabela de correspondencia e calculos no Polars, geocodigos como texto; teste a serializacao GeoJSON e zeros a esquerda.
