# Atlas Eleitoral — TSE, zonas eleitorais e mapas interativos

Protótipo independente em Python que agrupa votos de **seções → zonas → municípios**, com dados do TSE, **Polars** para dados eleitorais, GeoPandas para preparar geometrias e Folium para navegação no mapa.

## Contrato operacional

**`make` é o único ponto de entrada**. Não instalar dependências, rodar testes ou executar scripts manualmente fora do Makefile. `make bootstrap` cria `.venv`, instala `uv` via `pip install uv` dentro do ambiente e instala `requirements.txt` com `uv pip install -r requirements.txt`.

```powershell
# PowerShell com GNU Make instalado e Python 3.11+ disponível
make help
make bootstrap
make inspect FILE="C:/Downloads/votacao_secao_2026_RR.zip"
make import FILE="C:/Downloads/votacao_secao_2026_RR.zip"
make import-dir DIR="C:/Downloads"      # para os demais estados
make download UF=BR                  # votacao presidencial nacional
make ingest ANO=2026 UF=RR
make validate
make run
```

Para muitos estados, repita `make import FILE="..."` e depois rode `make ingest ANO=2026` (sem `UF`). Para facilitar a importação, **os originais são mantidos intactos** em `data/raw/2026/`. Há identificação de arquivos corrompidos; o processamento segue nos demais, grava um `ingest_manifest.json` e encerra com código diferente de zero quando há erros.

## Fontes oficiais e os arquivos deste lote

TSE: <https://dadosabertos.tse.jus.br/dataset/resultados-2026>. Os ZIPs por estado, `votacao_secao_2026_UF.zip`, incluem cargos estaduais. **Presidente não é incluído necessariamente nesses ZIPs.** Para ele, importe também o ZIP nacional específico: <https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_BR.zip>. O arquivo `BR` é processado separadamente e marcado com UF real da seção.

Na amostra fornecida, 10 ZIPs estaduais apresentaram CSVs legíveis de 26 colunas (`ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `DS_CARGO`, `NR_VOTAVEL`, `NM_VOTAVEL`, `QT_VOTOS` etc.). **O arquivo PR fornecido estava inválido**, com tamanho de cerca de 2 MB. Faça novo download do PR.

**Atenção:** os arquivos de votação por seção possuem uma linha por candidato/resultado por seção. A soma dos valores de `QT_VOTOS` pode incluir eleições para múltiplos cargos; não representa comparecimento eleitoral único. O painel calcula proporção entre votos nominais do **mesmo cargo e turno**, sem contar brancos e nulos no denominador. Votos do Senado com duas vagas não devem ser interpretados como comparecimento.

## Geografia

O TSE publica resultados por zona, mas um conjunto público uniforme de **polígonos oficiais de todas as zonas** não acompanha os CSVs. Para mapas coloridos, é necessário fornecer uma malha:

```powershell
# Forneça malha IBGE 2025 (GeoJSON, GeoPackage ou shapefile compactado em ZIP)
make geo-import FILE="C:/dados/BR_Municipios_2025.zip" LEVEL=municipio

# E a tabela oficial com a correspondência dos códigos TSE ↔ IBGE
make crosswalk FILE="C:/dados/municipio_tse_ibge.csv"

# Opcional: polígonos de zonas obtidos de fonte cartográfica confiável
make geo-import FILE="C:/dados/zonas_RMSP.geojson" LEVEL=zona
make run
```

A aplicação **não inventa divisões de zona dentro de municípios**. Sem polígonos de zonas, apresenta o mapa por municípios e tabela por zona. Uma malha de zona precisa ter os atributos `UF`/`SG_UF` e `NR_ZONA` (ou equivalentes reconhecidos); no mapa municipal, `CD_MUN` / `CD_GEOCMU` / `codigo_ibge` com código IBGE de 7 dígitos. Nunca fazemos junção pelo nome do município.

* Malha IBGE: <https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/15774-malhas.html>
* TSE/IBGE: <https://dadosabertos.tse.jus.br/dataset/codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge>

## Estrutura

```
Makefile                todos os pontos de entrada
app.py                  painel Streamlit / Folium
mapa_eleicoes/cli.py    importador, leitura ZIP em blocos, agregador, validação
requirements.txt        dependências gerenciadas por uv
 tests/                 testes unitários
 data/raw/ANO/          ZIPs imutáveis do TSE (ignorados pelo Git)
 data/processed/ANO/    CSV gzip por arquivo + manifestos (ignorados pelo Git)
 data/geo/              geometria normalizada para EPSG:4326 (ignorada)
 data/reference/        correspondência TSE/IBGE (ignorada)
```

### Limitações explícitas / roteiro

1. Cobertura nacional depende de importar todos os estados e o ZIP BR de Presidente; o lote atual é parcial.
2. O painel carrega CSVs.gz agregados; para análises completas de seções e abstenções, desenvolver pipeline complementar de detalhes e de `QT_COMPARECIMENTO` sem contar valores repetidos por votável.
3. Polígonos de zonas são opcionais; não confundir limites de municípios com limites de zonas.
4. Melhorias posteriores: catálogo TSE automatizado (downloads idempotentes), cache de regiões GeoParquet no futuro, validação por total oficial do TSE, testes de cobertura dos dois turnos, filtros interativos e múltiplos anos.
5. Não versionar dados brutos (`data/` está ignorado por `.gitignore`); manter manifesto, fonte e checksums para rastreabilidade.

**Licenças/dados:** Dados públicos do TSE e malhas do IBGE sujeitos a suas respectivas condições de uso e atribuição; interface independente, sem vínculo com o G1.
## Motor tabular Polars / compatibilidade geoespacial

- **Polars** processa lotes de linhas TSE, agrega votos, filtra, faz joins TSE/IBGE, calcula vencedores, detalha zonas e exporta CSV. Nenhum import direto de pandas no codigo da aplicacao ou pipeline.
- **GeoPandas** continua responsavel apenas por ler, transformar e exportar geometrias. A biblioteca possui dependencia interna de pandas; isto **nao** significa que a aplicacao use pandas como motor tabular.
- **Fronteira de tipos:** `mapa_eleicoes/geo_bridge.py` recebe `pl.DataFrame`, percorre `iter_rows(named=True)` para escalares Python e atribui listas de `str/int/float` a uma copia da malha. **Nao** usar `pl.DataFrame.to_pandas()`, `GeoDataFrame.merge(pl.DataFrame)` ou Arrow extension dtypes implicitamente; incompatibilidades desta camada eram um risco historico.
- Campos `uf`, `cd_municipio_tse`, `numero`, `codigo_ibge` sao sempre texto; `turno` e `zona` sao inteiros; `votos` e Int64. Leitura dos agregados usa `infer_schema=False` e casts explicitos; evita inferir codigo como float e perder zeros.
- O pipeline mantém `votos_UF.csv.gz` e `tse_ibge.csv` no mesmo formato de antes. Não é necessario reimportar ZIPs anteriores para trocar o dashboard.
- **Makefile continua sendo o unico ponto de entrada:** `make bootstrap`, `make test`, `make ingest`, `make validate`, `make run`.
- `st.dataframe` suporta Polars diretamente. Para mapas, conversao deliberada para registros Python previne dependencia da conversao Polars↔pandas↔GeoPandas, especialmente com colunas Arrow e nulos.

Criterios de validacao local: `make bootstrap`, `make test`, `make ingest ANO=2026 UF=RR`, `make validate ANO=2026`, `make run`. Confirme valores de votos identicos aos manifestos e teste poligonos municipais e zonas.
