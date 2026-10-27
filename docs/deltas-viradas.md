# Deltas e viradas

Nova página Streamlit separada em pages/1_Deltas_e_viradas.py, preservando app.py, cores e navegação da apuração.

## Fórmulas
- Saldo primeiro turno: Lula_1T - Flávio_1T.
- Saldo segundo turno: Lula_2T - Flávio_2T.
- Delta: saldo_2T - saldo_1T = delta_Lula - delta_Flávio.
- Delta positivo: vermelho #d60828, pró-Lula.
- Delta negativo: azul #272d97, pró-Flávio.
- Virada efetiva: saldos de sinais opostos estritos.

O cálculo usa votos nominais e número eleitoral, não nomes como chave. Exige ambos os turnos e candidatos disponíveis. Nunca preenche turno completamente ausente. Não representa transferência individual de eleitores. Empate em algum turno não é virada estrita.

Os municípios usam malha IBGE e de/para oficial TSE/IBGE por código. Áreas de zona são **aproximadas**, geradas por setores IBGE 2022 + pontos de locais TSE, não perímetros oficiais. Setas são simbólicas, não são deslocamentos geográficos.

## Operação
Executar apenas pelo Makefile:
- make test
- make preview ANO=2026
- make run ANO=2026

Para preparar zonas a partir desta branch: make zones-setup ZONE_UFS=SP. A correção de UF=SP fica na PR #10, ainda separada.

## Duas camadas de visualização

Na página **Deltas e viradas**, abra **Camadas** no canto superior direito do mapa:

1. **Divisões + setas** (inicial): mostra os limites dos municípios ou das zonas aproximadas, **sem preencher as regiões**. As setas vermelhas/azuis indicam o sentido da evolução relativa do saldo; comprimento cresce com a magnitude do delta, limitado à dimensão do polígono. A seta não representa deslocamento de eleitores.
2. **Áreas por delta (sem setas)**: pinta a região conforme o sinal de Δ (vermelho `#d60828` para Lula, azul `#272d97` para Flávio, neutro `#6272a4` para Δ = 0), **sem desenhar nenhuma seta**.

O controle de camadas é do Leaflet e funciona no navegador: ao ativar uma das opções, a outra é desligada sem rerun do Streamlit, mantendo zoom, centro e mapa-base OSM. Também é possível desligar as duas, deixando somente os contornos territoriais sobre o mapa-base.

**Desempenho:** polígonos geográficos serializados uma só vez, com coordenadas arredondadas a quatro casas decimais, reaproveitados pelos dois modos via troca de estilo JavaScript. As setas são um único GeoJSON com geometrias `MultiLineString`, sem milhares de instâncias de `Marker`. Regiões sem dados comparáveis conservam seus contornos, mas nunca recebem setas nem preenchimento eleitoral fictício. O filtro "Somente viradas" mantém as divisões territoriais visíveis.

**Escopo das divisas:** a camada territorial segue o detalhamento selecionado: municípios oficiais IBGE ou áreas **aproximadas** de zonas dentro de cada município. A UF selecionada delimita o recorte, e o mapa-base apresenta o contexto cartográfico das divisas estaduais. Não foi inventada uma malha oficial de zonas eleitorais.

**Tooltip:** informações em linhas separadas com saldos do 1º e 2º turnos, Δ, variações individuais e condição de virada. Não deve ocupar uma linha horizontal com todas as informações, como na primeira implementação.

### Validação local (sem comandos diretos)

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

Conferir os dois modos com UF=Todas e com UF selecionada, e também a mudança de modo ao aproximar/afastar e arrastar o mapa.


## Navegação hierárquica por zoom (revisão 27/10)

A página principal recebe o nome **Atlas Eleitoral**, não mais "app": o
entrypoint **`Atlas_Eleitoral.py`** executa o `app.py` original no mesmo
contexto do script, sem `st.navigation`/`st.Page`. O Streamlit identifica
"Deltas e viradas" automaticamente no diretório `pages/`. O Makefile
continua sendo a **única entrada** (`make preview` / `make run`), e a
lógica de apuração, os eventos Folium, a câmera e o foco de cidade em
`app.py` permanecem inalterados.

Na visualização **Divisões + setas**, o zoom do Leaflet determina o nível
das setas sem recarregar o Streamlit:

| Zoom | Setas | Base de cálculo |
| --- | --- | --- |
| 0–6 | **Estado: uma seta maior por UF** | Soma dos saldos/votos dos municípios com 1º e 2º turno comparáveis em cada UF |
| 7–10 | **Municípios** | Delta por município TSE associado ao polígono IBGE por código |
| 11+ | **Zonas dentro do município** (se preparadas) | Delta por (UF, município TSE, zona) e contornos aproximados do IBGE/TSE |

**Cobertura:** o agregado de UF é calculado sobre municípios com ambos os
turnos presentes nos Parquets carregados; não representa totalização completa
quando a cobertura é parcial. Quando o filtro *Somente viradas efetivas*
estiver ligado, cada nível mostra apenas unidades que efetivamente mudaram
o sinal do saldo (estado/município/zona), não apenas variações positivas ou
negativas. Estados, municípios e zonas usam as mesmas fórmulas e cores.

Para evitar picos de memória no mapa nacional, zonas geográficas de todo o
país **não são carregadas de uma só vez**. O detalhamento por zona é ativado
automaticamente após selecionar uma UF cujo arquivo
`data/geo/zonas/zonas_municipio_UF.geojson` exista. Sem esse arquivo,
o zoom máximo conserva as setas e os limites municipais. Não fabrica
zonas, polígonos nem centróides de locais de votação.

A visualização alternativa **Áreas por delta (sem setas)** permanece
disponível no controle Leaflet; no zoom máximo (quando houver geometria de
zona preparada) o preenchimento passa das áreas municipais para as áreas
aproximadas das zonas, preservando o contexto dos limites municipais.
Em zoom afastado o preenchimento permanece municipal; somente as setas
são agregadas por UF. A direção das setas é simbólica, não movimento de
eleitores. As setas estaduais são posicionadas sobre um município existente
próximo ao centro da UF; não se usa `union_all` nem dissolução territorial.

### Validação da alteração

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

Confirmar nome **Atlas Eleitoral** no menu, alternância de camadas,
escala de setas com zoom (6 → 7 → 11), persistência do enquadramento ao
aproximar/afastar e fallback municipal em UFs sem geometria de zona.


### Regressão de foco municipal: restauração do entrypoint

O wrapper `atlas.py` com `st.navigation` foi removido após o relato de
que o clique no município não enquadrava mais a cidade na página
principal. Para não arriscar o ciclo de vida dos callbacks do
`st_folium`, o Makefile volta a iniciar um script de página diretamente,
agora chamado `Atlas_Eleitoral.py`. Esse script executa literalmente
o código existente de `app.py` no mesmo escopo; a navegação secundária
é descoberta automaticamente pelo Streamlit em `pages/`.

**Importante:** depois de atualizar a branch, **encerre o servidor
Streamlit antigo** (`Ctrl+C`) e inicie novamente com `make preview
ANO=2026`. Uma execução que já ativou `st.navigation` não volta para
a navegação automática somente por hot reload; requer novo processo.
O teste estrutural verifica a preservação de `CityFocus` e
`render_explorer`, mas a confirmação de clique/zoom exige navegador.
