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

17. **Base cartográfica pública:** não usar tiles CARTO sem chave de API; preferir OpenStreetMap com atribuição visível. Filtro de cor só nos tiles, nunca nos polígonos eleitorais; testar HTML gerado pelo Folium.
18. **Streamlit:** substituir `use_container_width` de elementos nativos por `width="stretch"`. Não confundir esse parâmetro com a API própria do `st_folium`.

19. **Paleta eleitoral estável:** candidato/legenda 13 (PT) em vermelho #ff5555 e 22 (PL) em azul #3b82f6; nunca inferir por ordenacao no ranking, nem pelo nome Lula. Para demais numeros, cores fixas por prefixo de NR_VOTAVEL. Validar partidos no dataset oficial quando houver coligacao/candidatura excepcional.
20. **Make geo-import sem arquivo:** ausência de FILE para municipios deve configurar fontes oficiais com cache; LEVEL=zona requer arquivo proprio, jamais fabricar zonas a partir de municipios. Cobrir os dois casos em testes.

21. **Filtros de cargos e turnos:** criar a lista de cargos apos filtrar por ano/UF, mas antes de aplicar filtro de turno. Exibir apenas turnos existentes para cargo selecionado. `make offices ANO=2026` deve mostrar cargos reais por turno/UF e diagnosticar `votos_BR.csv.gz`, sem inventar Presidente.

22. **Dataset final de consumo:** toda consulta do Streamlit deve vir de `data/serving/ANO/votos_*.parquet`, gerado por `make run` ou `make prepare-serving`; brutos e auxiliares munzona nao sao carregados pelo painel. `catalog.json` deve registrar proveniencia, UFs e turnos sem prometer cobertura nacional nao auditada.
23. **Segundo turno:** oferecer 1 e 2 no seletor; indicar claramente `sem dados` quando o conjunto oficial ainda nao contem turno do cargo. Nunca preencher resultados do 2º turno a partir do 1º nem inventar totalizacoes. Atualizacao oficial BR seletiva usa `make refresh-data`; `ALL=1` confere todas fontes uma vez ao dia.
24. **UX voltada ao leitor:** nao expor comandos Makefile, paths de projeto ou stack trace em avisos normais do dashboard. Instrucoes operacionais ficam somente no README/CLI. Se nao houver malha real de zona eleitoral, nao oferecer radio de geometria de zona; filtro numerico de zona e tabela continuam disponiveis, com mapa municipal corretamente rotulado.
25. **Integridade:** `make run` sincroniza fontes, geografia, ingestao, Parquets finais e valida cobertura antes de abrir painel; erros de download nao sobrescrevem arquivo integro. `make preview` consulta Parquets locais para laboratorio com cobertura parcial.

26. **Apuração por seção:** ingestão independente preserva `NR_SECAO`, `NR_ZONA`, `NR_TURNO`, candidato, voto e UF; Parquets por arquivo em `data/serving/ANO/secoes/`. Não reconstruir seção a partir do agregado municipal e nunca misturar fontes munzona ao mesmo total.
27. **Localização de seções:** usar exclusivamente coordenadas TSE do cadastro `eleitorado_local_votacao_2026`, vinculadas por município TSE+UF+zona+seção+turno. Pontos são dos *locais de votação*; múltiplas seções podem compartilhar um local. Sem coordenadas, mostrar na tabela e não inventar pontos, centroides ou polígonos.
28. **Gradiente por porcentagem:** aplicar percentuais de votos nominais do cargo/turno ao candidato do recorte, mantendo vermelho 13 e azul 22; zeros não são confundidos com dados inexistentes. Mostrar legenda e percentuais numéricos em tooltip. Não confundir com margem em pontos percentuais.
29. **Performance:** agregação Polars incremental/shards, lazy sink_parquet; evitar centenas de milhares de marcadores e exigir município para mapa detalhado, com contagem de locais não mostrados.

30. **Mapa nunca vazio por falta de seleção manual:** modos Automático e Seção eleitoral (locais) devem apresentar sempre a malha municipal. Só mostrar localização de seção como ponto oficial TSE; não exigir filtros antes de desenhar o Brasil.
31. **Navegação pelo mouse:** tooltip municipal no próprio Leaflet (sem return_on_hover) e renderização de locais após zoom urbano/click sobre polígono real; usar st_folium com key estável, zoom/center persistentes e overlays FeatureGroup dinâmicos. Seleção manual e automática coexistem.
32. **Performance e integridade:** resolver município com índice espacial GeoPandas; para pontos carregar somente o Parquet da UF e municípios em foco, sem varrer todos os arquivos no navegador. Clique fora de polígonos nunca vira município mais próximo; sem coordenadas oficiais não criar marcadores.
