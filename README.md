# Explorador automático — navegação diretamente no mapa

O Atlas agora começa sempre com uma malha geográfica **visível**, mesmo
quando há resultados por seção eleitoral disponíveis. A antiga exigência
de selecionar UF e município antes de mostrar o mapa foi removida.

Inspirado na navegação interativa por mapa, mas com código próprio:
- **Hover:** o tooltip de município mostra os dados no navegador,
  sem fazer rerun do Streamlit a cada movimento do mouse;
- **Clique sobre polígono municipal:** aproxima diretamente a cidade
  identificada pelo polígono IBGE real;
- **Scroll/zoom:** em nível urbano (zoom 10 ou maior) o centro do viewport
  determina o município em foco, e o Atlas consulta automaticamente
  os Parquets por seção da sua UF e os locais georreferenciados do TSE;
- **Locais:** pontos agrupados por local de votação, com popup detalhando
  seções e porcentagens. Os pontos não representam limites territoriais;
- **Controles:** filtros UF, município, cargo, turno e zona seguem
  disponíveis; o modo inicial **Automático** não exige uso deles.
  `Município` e `Seção eleitoral (locais)` continuam como opções.

O mapa preserva zoom e centro durante as interações e limita a
consulta de pontos ao município focado. Nenhum download de dados é
disparado pelo próprio Streamlit; para preparar tudo antes da
interface, use o Makefile.

```powershell
git status -sb
git fetch origin --prune
git switch feature/geo-ibge-tse-crosswalk
git merge --ff-only origin/feature/geo-ibge-tse-crosswalk
make test
# Dados e locais ja preparados podem ser visualizados diretamente:
make preview ANO=2026
# Fluxo integral: importacao, malhas, secoes e Streamlit:
make run ANO=2026
```

A navegação do G1 é referência conceitual, não dependência:
https://g1.globo.com/politica/eleicoes/2026/mapas/mapa-de-apuracao/presidente/brasil.ghtml

---
# Gradiente eleitoral e detalhamento por seção (2026)

O Atlas utiliza a **mesma paleta estável por número eleitoral** (PT/13 vermelho,
PL/22 azul, demais partidos cores distintas).

- **Vencedor por região:** a cor é a do líder e a intensidade é a
  **diferença em pontos percentuais para o 2º colocado**, em quatro classes
  (0–5, 5–10, 10–20 e acima de 20 p.p.). Empate no topo tem cor neutra.
  No 2º turno o líder sempre tem 50% ou mais; por isso a escala usa a
  margem, e não o percentual do líder, que desperdiçaria metade da escala.
- **Votação de candidato:** gradiente contínuo de 0% a 100% do candidato.
- O tooltip mostra 1º e 2º colocados (percentual e votos) e a diferença.

Percentuais usam votos **válidos** do cargo/turno (nominais + legenda),
**não** brancos, nulos, aptos, abstenções ou todos os cargos somados.
Se o arquivo nacional `votos_BR` e um arquivo estadual trouxerem o mesmo
(UF, cargo, turno), vale o nacional e as linhas estaduais repetidas são
descartadas, com aviso no painel.

## Mapa por seção eleitoral

O arquivo TSE `votacao_secao_2026_UF.zip` inclui `NR_ZONA` e
`NR_SECAO`. O Atlas passou a preservar cada seção, candidata/candidato,
cargo e turno em Parquets de `data/serving/ANO/secoes/`. A agregação
municipal existente continua separada — **não duplicar** os totais.

A posição espacial vem de **outra fonte oficial**, o cadastro
[Eleitorado por local de votação — 2026](https://dadosabertos.tse.jus.br/dataset/eleitorado-2026),
que possui coordenadas dos locais de votação, não fronteiras de seções.

Link oficial do ZIP:

`https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip`

### Instruções PowerShell

```powershell
git fetch origin --prune
git switch feature/geo-ibge-tse-crosswalk
git merge --ff-only origin/feature/geo-ibge-tse-crosswalk

make test

# Preparacao por secao; processamento incremental, uma primeira passagem
# sobre cada ZIP bruto, sem baixar os resultados ja presentes.
make prepare-sections ANO=2026

# Downloads oficiais e cache da posicao dos locais TSE.
make prepare-locations ANO=2026

# Abre os resultados locais sem disparar reprocessamento dos ZIPs grandes.
make preview ANO=2026

# Operacao integral padrao (sincroniza, valida, prepara tudo e abre app).
make run ANO=2026
```

Se o cadastro de locais foi baixado manualmente:

```powershell
make prepare-locations ANO=2026 SECTION_FILE="C:/Users/dante/Downloads/eleitorado_local_votacao_2026.zip"
```

**Como usar:** selecione uma UF e um município, depois **Detalhamento
geográfico → Seção eleitoral (locais)**. Os pontos representam
**locais oficiais**; várias seções podem compartilhar o mesmo ponto.
Cada popup relaciona números de seção, total de votos válidos,
candidato com mais votos e respectivo percentual. O seletor de seção
filtra os votos sem fabricar uma forma territorial para a seção.

Os locais sem coordenadas continuam consultáveis em tabelas; não
são deslocados artificialmente para o centro do município.
Para limitar uso de memória e tempo de renderização, a interface não
desenha de uma vez todos os locais do Brasil: é necessário selecionar
UF e município. O mapa limita a quantidade de locais por renderização
e informa a contagem quando uma seleção é muito ampla.

**Precisão:** a mesma seção pode mudar de local entre os turnos;
a chave de vinculação inclui `UF + município TSE + zona + seção + turno`.
Uma representação por ponto **não** define área territorial, perímetro
da zona ou endereço residencial de eleitor.

---

# Atlas Eleitoral — Dados prontos para o mapa

**Contrato da aplicacao (outubro/2026):** a interface Streamlit
consome exclusivamente os **Parquets finais** em
`data/serving/ANO/votos_*.parquet`. Ela nao baixa dados, nao transforma
ZIPs e nao exibe instrucoes de terminal para os visitantes.

O comando operacional `make run ANO=2026` agora encadeia:
1. Sincronizacao oficial seletiva do TSE (`BR` e `PR`), incluindo
   tentativa diaria de atualizar `BR` quando faltam resultados do 2º turno;
2. Malha municipal oficial do IBGE e de/para TSE/IBGE em cache;
3. Ingestao/validacao dos ZIPs TSE, mantendo `munzona` em fluxo distinto;
4. Materializacao de Parquet Polars e do `catalog.json`, com cobertura
   de UFs, cargos e turnos efetivamente presentes;
5. Checagem de chaves geograficas e abertura do Streamlit.

Os dois turnos aparecem no seletor. Quando faltam dados de determinado
cargo e turno, o painel os identifica como **sem dados**; nao fabrica
votos. Na ausencia de poligonos reais de zona eleitoral, usa somente
a malha municipal e permite filtrar votos por zona em tabela/mapa,
sem chamar limites municipais de zonas.

```powershell
# Na raiz do repositorio, apos atualizar feature/geo-ibge-tse-crosswalk:
make test
make offices ANO=2026

# Atualizar o conjunto oficial nacional inteiro (pode consumir varios GB).
# ALL=1 verifica cada uma das 28 fontes no maximo uma vez por dia;
# FORCE=1 obriga verificacao mesmo no mesmo dia.
make refresh-data ANO=2026 ALL=1

# Prepara completamente dados + geometria + Parquets e abre interface.
make run ANO=2026

# Caso uma fonte oficial indisponivel impeça o run, inspecionar
# os resultados locais existentes, sem reimportar brutos corrompidos:
make preview ANO=2026
```

`make run SYNC=0` pode ser usado **somente para trabalho local/offline**
quando a verificacao remota nao for desejada; continua exigindo
integridade de quaisquer ZIPs que estejam presentes. Se o ZIP do
Parana ainda estiver ausente e a fonte remota indisponivel, a
cobertura nao sera considerada nacional. Para recuperar o 2º turno
presidencial sem atualizar todos os outros estados:
`make refresh-data ANO=2026 UFS=BR FORCE=1`.

O portal do TSE indica atualizacao de arquivos por secao ao final de
cada turno; isto **nao garante** que uma copia local ja contenha o
segundo turno. O catalogo confirma exatamente quais registros existem.
Fontes de resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2026.

---

## Correção do comando geográfico e cores eleitorais

O alvo `make geo-import` agora aceita **uso sem `FILE`**, equivalente
à preparação automática da malha municipal oficial (`geo-setup`, com
cache e de/para TSE/IBGE). O comportamento manual permanece disponível:

```powershell
# Fontes municipais oficiais com cache
make geo-import
# Mesmo setup com ano explicito
make geo-import GEO_YEAR=2025

# Malha que voce forneceu
make geo-import FILE="C:/Downloads/BR_Municipios_2025.zip" LEVEL=municipio

# Limites eleitorais sao OUTRO dataset e exigem arquivo proprio
make geo-import FILE="C:/Dados/zonas.geojson" LEVEL=zona

# Usar os dados ja processados; nao reprocessa todos os ZIPs do TSE
make test
make preview
```

**Cores do Atlas, por numero da legenda:** PT / 13 **vermelho**
(`#ff5555`), PL / 22 **azul** (`#3b82f6`).
As demais legendas recebem outras cores consistentes entre filtros e
ordem dos resultados. A fonte atualmente armazenada, `NR_VOTAVEL`,
é o número do candidato; a regra usa os dois primeiros dígitos para
candidaturas nominais, sem inferir partido por nome ou por posição
no ranking. Isto é uma convenção visual do Atlas, não uma classificação
oficial de cores pelo TSE. Em casos especiais/coalizões, validar a
legenda no dataset oficial de candidaturas.


## Correção do seletor: cargos do primeiro turno

**Problema encontrado na captura:** ao escolher `Turno 2`, o antigo painel
filtrava todos os registros antes de construir a lista de cargos. Assim,
os cargos disputados apenas no **primeiro turno** (Senador, Deputado
Federal, Deputado Estadual/Distrital) desapareciam do seletor.
A ausência de Presidente no segundo turno também pode ser uma ausência
efetiva no arquivo `BR`, e deve ser verificada, não inventada.

**Contrato novo:** ano → UF → **Cargo** → turnos disponíveis para o cargo
→ município → zona. O padrão prioriza `Presidente` se estiver presente
nos dados; caso contrário usa o primeiro cargo disponível. Para cargos
de turno único, só aparece `1`. Isto não cria dados ausentes.

Diagnóstico com o Makefile (sem processar ZIPs de novo):

```powershell
git fetch origin --prune
git switch feature/geo-ibge-tse-crosswalk
git merge --ff-only origin/feature/geo-ibge-tse-crosswalk

make test
make offices ANO=2026
make preview
```

`make offices` percorre os CSV.gz de `data/processed/2026` e informa
os cargos encontrados em cada turno e quantidade de UFs/arquivos.
A linha `[OFFICES] Fonte BR` mostra os cargos do arquivo nacional
`votos_BR.csv.gz`. Se este faltar, o comando avisa; para recuperá-lo
use `make download ANO=2026 UF=BR` e `make ingest ANO=2026 UF=BR`.
A presença de um arquivo **não garante** Presidente nos dois turnos:
o catálogo reflete somente as linhas disponíveis.

# Atlas Eleitoral — TSE, zonas eleitorais e mapas interativos

Protótipo independente em Python que agrupa votos de **seções → zonas → municípios**, com dados do TSE, **Polars** para dados eleitorais, GeoPandas para preparar geometrias e Folium para navegação no mapa.


## Correção: arquivos locais em C:/Downloads

Os anexos enviados em uma conversa **não aparecem automaticamente** no disco Windows. Primeiro, salve os ZIPs do TSE em `C:/Downloads`. O comando `make run` sem `DIR` procura apenas em `data/`, `data/incoming/` e `data/raw/ANO/`.

No PowerShell, com a branch da PR atualizada e a partir da raiz do repositorio:

```powershell
make data-scan ANO=2026 DIR="C:/Downloads"
# Deve listar os arquivos "votacao_secao_2026_XX.zip" e os tres "*munzona_2026.zip".
make run ANO=2026 DIR="C:/Downloads"
# Se quiser pular a transformacao auxiliar grande, mantenha os votos por secao:
make run ANO=2026 DIR="C:/Downloads" AUX=0
# Apos a preparacao (e ao encerrar a interface), gerar o pacote:
make data-pack ANO=2026
```

`make data-scan` verifica os nomes/quantidades da pasta sem extrair/processar. `make run DIR=...` copia atomica e incrementalmente os ZIPs reconhecidos para `data/raw/2026/`, verifica a estrutura ZIP e registra qualquer erro no `data/processed/2026/prepare_manifest.json`. Se houver um ZIP corrompido (o arquivo PR anterior era um exemplo), os arquivos saudaveis continuam sendo importados, mas a preparacao encerra com falha ate que o corrompido seja corrigido.

O comando `make import-dir` legado considera apenas os ZIPs `votacao_secao_*`; use **`make run DIR=...`** para incluir tambem os tres datasets agregados `munzona`. Sem arquivos reconhecidos, nenhum bundle sera gerado; confira se os downloads sao arquivos ZIP reais (e nao atalhos ou links). O `make data-pack` cria `data/bundles/tse_raw_2026_bundle.zip` somente com os originais que ja foram importados.

## Mapas-base e compatibilidade de interface (outubro/2026)

O raster `CartoDB dark_matter` passou a exigir uma chave de API e
produzia a marca d'agua `API KEY REQUIRED` em todos os tiles. O painel
agora usa **OpenStreetMap**, que funciona sem chave para uso moderado,
com filtro CSS aplicado somente aos tiles para manter o visual
escuro/Dracula. As cores dos resultados, geometrias e tooltips
continuam independentes da aparencia do mapa-base.

A tabela Streamlit utiliza `width="stretch"` no lugar do antigo
`use_container_width=True`. A integracao `st_folium` continua usando
seu parametro proprio de largura, documentado por essa biblioteca.

O tooltip municipal exibe **nome do municipio + codigo IBGE + resultado**;
o join eleitoral permanece feito **apenas pelo codigo IBGE**.

```powershell
git fetch origin --prune
git switch feature/geo-ibge-tse-crosswalk
git merge --ff-only origin/feature/geo-ibge-tse-crosswalk
make test
make preview
```

No filtro de **DF/Brasilia**, ver somente **um poligono municipal**
e esperado; mapa de zona exige fonte geoespacial propria. O
`make preview` nao precisa reprocessar os ZIPs gigantes nem baixar
a malha ja preparada.

## Mapa municipal oficial: IBGE + correspondencia TSE/IBGE

**O mapa precisa de dois datasets adicionais:** (1) geometrias municipais IBGE e
(2) de/para dos codigos de municipios, publicados pelo TSE. Ambos sao
referencias geograficas, independentes dos ZIPs de votacao por secao.

**Fontes oficiais verificadas:**
- IBGE, `BR_Municipios_2025.zip` (aprox. 226 MB): <https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_Municipios_2025.zip>
- TSE, `municipio_tse_ibge.zip`: <https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip>
- Portal TSE: <https://dadosabertos.tse.jus.br/dataset/codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge>

A malha IBGE 2025 contem **5.573 geocodigos territoriais**, incluindo
municipios e unidades especiais; nao interpretar automaticamente esse
total como quantidade de cidades com votacao. A compatibilidade 2025/2026
deve ser avaliada na verificacao de cobertura.

### Preparacao inicial (Windows / PowerShell)

```powershell
# Fluxo Git: revisar feature branch antes de merge
git fetch origin
git switch --track origin/feature/geo-ibge-tse-crosswalk

# Testar alteracoes com Makefile
make test

# Download e preparacao; faz cache dos ZIPs, sem colocar arquivos grandes no Git
make geo-setup GEO_YEAR=2025

# Cobertura por codigos oficiais: sem inferir municipios por nome
make geo-check ANO=2026

# Painel com as votacoes ja preparadas, mesmo com o PR defeituoso pendente
make preview

# Depois de substituir o ZIP invalido do PR e validar todos os brutos
make run ANO=2026
```

Se a rede nao permitir downloads, forneca os arquivos baixados por outro
meio (sem executar Python diretamente):

```powershell
make geo-setup GEO_YEAR=2025 MALHA="C:/Downloads/BR_Municipios_2025.zip" CROSSWALK="C:/Downloads/municipio_tse_ibge.zip"
make geo-check ANO=2026
make preview
```

Para atualizar a geometria local com outras tolerancias, use
`make geo-setup GEO_YEAR=2025 FORCE=1 SIMPLIFY_METERS=500`.
Isso **nao** reprocessa os votos; apenas as referencias espaciais.

- Malha original cacheada: `data/geo/source/BR_Municipios_2025.zip`.
- Malha simplificada: `data/geo/municipios.geojson` (EPSG:4326).
- De/para original: `data/reference/source/municipio_tse_ibge.zip`.
- De/para normalizado: `data/reference/tse_ibge.csv`.
- Metadados de geografia: `data/geo/official_sources.json`.
- Verificador: `make geo-check` informa quantas chaves TSE nao encontraram
  codigo IBGE e quantos codigos IBGE nao encontraram poligono.

**Garantias:** a chave de join e sempre `uf+cd_municipio_tse`; os codigos
IBGE sao strings de 7 digitos. Se a UF nao existir no CSV do TSE, ela
e derivada do prefixo oficial de 2 digitos do codigo IBGE. Dados de
geometria sao tratados com GeoPandas e valores tabulares com Polars;
nunca ha `to_pandas()` nem `GeoDataFrame.merge(Polars)`.

**Limite geoespacial:** poligonos de municipios nao equivalem a limites
das zonas eleitorais. O mapa de zonas continuara condicionado a fontes
cartograficas proprias, e cada zona pode cortar ou compartilhar territorios.

## Fluxo automatizado de dados brutos: make run

**Regra:** `make run` agora executa `make prepare-data` ANTES de iniciar o Streamlit. A preparacao e incremental: muda apenas arquivos de origem modificados (tamanho/mtime e hash SHA-256 nos manifestos); preserva os ZIPs TSE, processa os CSVs de votacao por secao para o mapa e materializa os 3 datasets `munzona` em arquivos Parquet separados. Isso pode exigir muitos gigabytes de espaco e levar bastante tempo na primeira execucao.

### Onde colocar os arquivos

Existem tres opcoes, sem descompactar manualmente os ZIPs individuais:

1. Colocar `votacao_secao_2026_UF.zip` (incluindo `BR`) e os 3 `*munzona_2026.zip` em `data/` ou `data/incoming/`. `make run` os copia para `data/raw/2026/` e processa.
2. Colocar esses ZIPs diretamente em `data/raw/2026/`, mantendo seus nomes originais.
3. Colocar `tse_raw_2026_bundle.zip` diretamente em `data/` ou `data/incoming/`. `make run` extrai e valida o manifesto/hash antes de processar.

**Nao versionar nenhum ZIP ou Parquet em Git.** O ZIP consolidado e ZIP64, usa `ZIP_STORED` para nao recomprimir um ZIP e inclui `manifest.json` com checksums. Ele pode ser bem grande.

### Passos no PowerShell

```powershell
# Repositorio clonado e na branch da PR
git status -sb
git fetch origin --prune
git switch feature/initial-tse-atlas-make-uv
git merge --ff-only origin/feature/initial-tse-atlas-make-uv

# Quando todos os arquivos originais ja estao no mesmo diretorio
make bootstrap
make import-dir DIR="C:/Downloads/TSE" ANO=2026
make doctor ANO=2026

# Executa TODAS as rotinas e inicia o mapa (equivale a prepare-data + Streamlit)
make run ANO=2026

# Depois de organizar os brutos, criar o ZIP consolidado localmente
make data-pack ANO=2026
# Resultado: data/bundles/tse_raw_2026_bundle.zip
```

Se os arquivos estiverem em `data/`, **nao e necessario executar import-dir**; basta `make run`.

Para usar o bundle em outro clone do projeto:

```powershell
# Copiar o bundle para data/tse_raw_2026_bundle.zip
make data-unpack ANO=2026 BUNDLE="data/tse_raw_2026_bundle.zip"
make run ANO=2026
```

### Alvos e politicas

| Alvo | Operacao |
| --- | --- |
| `make prepare-data ANO=2026` | staging, leitura ZIPs, secao -> CSV.gz, 3 munzona -> Parquet, verificacao de totais |
| `make run ANO=2026` | `prepare-data` + Streamlit |
| `make run ANO=2026 AUX=0` | roda secao/validacao sem criar Parquets gigantes munzona |
| `make data-pack ANO=2026` | pacote de brutos para transferencia, sem incluir derivados |
| `make data-unpack ANO=2026 BUNDLE=...zip` | extrai bundle verificando SHA-256 e sem sobrescrever arquivos divergentes |
| `make validate ANO=2026` | compara votos agregados com seus manifestos |
| `make doctor ANO=2026` | mostra brutos, saidas e recursos disponiveis |

**Datasets distintos nao sao somados entre si:** `votacao_secao_2026_{UF}.zip` alimenta `data/processed/2026/votos_{UF}.csv.gz`. `votacao_candidato_munzona_2026.zip`, `votacao_partido_munzona_2026.zip` e `detalhe_votacao_munzona_2026.zip` vao para `data/processed/2026/aux/<arquivo>/part-*.parquet`, com todas as colunas inicialmente como texto (schema original preservado). Eles nao entram no denominador dos votos por secao, evitando dupla contagem.

O arquivo `votacao_secao_2026_PR.zip` recebido antes apresentou erro de integridade. **Substitua esse ZIP por uma copia valida.** O `make run` aborta ao detectar bruto corrompido e grava `prepare_manifest.json` com a causa, para nao exibir um mapa que pareca completo sem estar.

**As malhas IBGE e o de/para TSE/IBGE ainda sao dependencias separadas do mapa colorido.** Sem eles, o dashboard abre as tabelas mas nao fabrica os limites das zonas. Use `make geo-import` e `make crosswalk` como documentado abaixo.

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

Na primeira amostra fornecida, 10 ZIPs estaduais apresentaram CSVs legíveis de 26 colunas (`ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `DS_CARGO`, `NR_VOTAVEL`, `NM_VOTAVEL`, `QT_VOTOS` etc.). **O arquivo PR fornecido estava inválido**, com tamanho de cerca de 2 MB. Faça novo download do PR.

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
