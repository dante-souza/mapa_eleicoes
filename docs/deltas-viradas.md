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

1. **Divisões + setas** (inicial): mantém as divisas estaduais e as setas coloridas no nível geográfico do zoom. Municípios e zonas preservam hover e ficam sem bordas internas, exceto o contorno da região clicada. As setas não representam deslocamento de eleitores.
2. **Áreas por delta (sem setas)**: pinta estados/municípios/zonas conforme o zoom e o sinal de Δ (vermelho `#d60828` para Lula, azul `#272d97` para Flávio, neutro `#6272a4` para Δ = 0), **sem setas e COM divisas finas do nível exibido**, além das estaduais.

O controle usa **dois botões de opção (radio)** implementados no Leaflet: exatamente um modo permanece ativo, sem checkboxes concorrentes ou seleção do tile OpenStreetMap. A alternância não faz rerun do Streamlit, preserva o centro/zoom e mantém o mapa-base OSM.

**Desempenho:** polígonos geográficos serializados uma só vez, com coordenadas arredondadas a quatro casas decimais, reaproveitados pelos dois modos via troca de estilo JavaScript. As setas são desenhadas num único Canvas Leaflet em pixels, sem milhares de instâncias de `Marker`; as feições eleitorais continuam no GeoJSON para os tooltips. Regiões sem dados comparáveis mantêm a área interativa para hover, mas não recebem setas nem preenchimento eleitoral fictício. O filtro "Somente viradas" mantém apenas as divisas estaduais visíveis; os polígonos de municípios/zonas continuam interativos, sem linhas.

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
Em zoom afastado **tanto os contornos quanto o preenchimento e as setas são estaduais**. As UFs são construídas por união das geometrias municipais do IBGE, sem limites retangulares artificiais. A direção das setas é simbólica, não movimento de
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


### Hotfix: clique/zoom da página principal (segunda intervenção)

A restauração anterior do entrypoint não foi suficiente: o usuário relatou
que clicar nos municípios continuava sem produzir o enquadramento esperado.
Foi feita uma correção na **interação Leaflet**, isolada dos deltas:

- `CityFocus` agora registra `click` diretamente em cada feição GeoJSON,
  em vez de depender de `e.layer` num evento propagado do grupo.
- Há fallback no clique do mapa: resolve a geometria municipal pelo ponto
  clicado quando Canvas/pane não entrega o evento da feição. Não processa
  duas vezes o mesmo clique propagado de um polígono.
- `map.fitBounds` é acionado **antes** do repaint de todos os municípios,
  mantendo a resposta da câmera ágil no mapa nacional.
- No detalhamento puramente **Município**, `st_folium` não envia clique
  de volta ao servidor, evitando reinicializações desnecessárias.
- Quando o clique é usado para carregar zonas/locais em modo **Automático**,
  o município focado é guardado com o escopo dos filtros e usado para
  restaurar a câmera após rerun.
- Novos testes verificam o clique nas feições, o fallback no mapa, a
  restauração do foco e a **serialização pela ponte streamlit-folium**,
  não apenas o HTML gerado pelo Folium.

A aplicação **não muda** as paletas, o modelo de votos nem as geometrias.
O patch está na PR #11, ainda em revisão. Os testes e o clique real
precisam ser confirmados na máquina do operador.

No PowerShell, após `Ctrl+C` para encerrar o Streamlit:

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

Validar na página Atlas Eleitoral primeiro com **Detalhamento geográfico =
Automático**: clicar num município deve alterar imediatamente a câmera,
destacar a região e escurecer o entorno; arrastar/usar o scroll deve
continuar operando; Esc ou Voltar retorna ao mapa original. Repetir com
**Município** e selecionar novamente Automático para testar o rerun
com carregamento de locais. A página de deltas não altera esses controles.

## Escalas territoriais completas e setas legíveis (revisão adicional)

**Apenas o mapa de Deltas e viradas foi modificado nesta revisão.**
O Atlas Eleitoral principal, o foco municipal, os cliques, o zoom e a navegação
que já voltaram a funcionar não foram alterados.

| Zoom Leaflet | Divisões e setas | Área preenchida |
| --- | --- | --- |
| 0–6 | Uma borda **estadual** e uma seta **maior** por UF com delta | Estado colorido pelo delta agregado |
| 7–10 | Bordas municipais e setas individuais (com limitação de sobreposição visual) | Municípios coloridos pelo delta |
| 11+ | Bordas e setas das zonas aproximadas se a UF tiver malha preparada; sem isso, municípios | Zonas (ou municípios na ausência da malha) |

As setas deixam de ser linhas de comprimento fixado em graus de latitude.
São símbolos sobre um **único Canvas Leaflet**, com comprimento de referência
em **pixels** (estado 40–68 px, município 21–37 px e zona 16–27 px),
espessura diferente para cada nível e contorno claro para contrastar
com os tiles escuros. O sinal do delta ainda determina a direção e
a cor original do Atlas (vermelho `#d60828`, azul `#272d97`).
O tamanho também varia com a magnitude relativa, sem alegar transferência
individual de votos nem movimento geográfico real.

Os municípios muito próximos podem compartilhar poucos pixels na escala
intermediária: para evitar uma nuvem ilegível de setas, o Canvas prioriza
visualmente o maior delta absoluto por pequena célula de tela. **Os votos
e agregados não são descartados nem alterados**; apenas parte dos símbolos
sobrepostos fica oculta até o usuário aproximar.

O modo **Áreas por delta (sem setas)** mantém as mesmas três escalas e
esconde todas as setas. A alternância no controle de camadas e o zoom
ocorrem inteiramente no Leaflet, sem reiniciar a página.

A geometria de zona continua condicionada à seleção de uma UF com arquivo
`zonas_municipio_UF.geojson` pronto. No mapa nacional, as 27 malhas zonais
não são carregadas simultaneamente por razões de memória. Os contornos
estaduais são criados a partir da união de municípios IBGE 2025, e zonas
continuam explicitamente classificadas como aproximações IBGE/TSE.

### Validação

Depois de atualizar a branch e reiniciar o servidor, confirme que:
- No zoom nacional só há fronteiras estaduais e setas grandes por UF.
- Ao cruzar o zoom 7 aparecem os municípios com setas legíveis.
- No zoom 11+, com uma UF preparada, surgem as zonas aproximadas e suas setas.
- Em **Áreas por delta**, os preenchimentos seguem o mesmo nível, sem setas.
- A página **Atlas Eleitoral** mantém intacto o clique e o foco municipal.

## Ajuste de legibilidade — somente divisas estaduais

Na revisão mais recente da página de deltas:

- O mapa mostra **somente contornos dos estados** em todos os zooms (0–6
  estados, 7–10 municípios, 11+ zonas quando disponíveis). As áreas
  territoriais internas continuam calculadas e representadas para
  hover/tooltips, mas **não desenham divisas municipais ou zonais**.
- O contorno estadual fica numa camada **não interativa** e acima do
  preenchimento; por isso o mouse sobre município/zona continua mostrando
  nome da região, saldos 1T/2T, Δ, variações individuais e virada.
- Os perímetros estaduais de polígonos derivados da união IBGE são
  desenhados somente pelos anéis externos. Buracos interiores da
  simplificação municipal não aparecem como riscos ou falsas fronteiras.
- As setas usam apenas vermelho `#d60828` ou azul `#272d97`,
  **sem contorno branco nem halo**. O comprimento e a espessura por
  zoom continuam calculados em pixels e permanece a redução de
  sobreposições em áreas muito densas.
- O modo **Áreas por delta (sem setas)** conserva o preenchimento por nível
  de zoom, com divisas finas municipais/zonais ou estaduais conforme a escala.
- **Escopo estrito:** alterados somente `mapa_eleicoes/swing_layers.py`,
  `tests/test_swing_layers.py` e esta documentação. O Atlas Eleitoral
  principal, `app.py`, `map_focus.py` e `interactive_map.py` não foram
  tocados nesta revisão.

### Verificações antes de merge

Após `make test` e `make preview ANO=2026`, conferir que:
1. O mapa nacional e os zooms altos exibem contornos **somente estaduais**.
2. O hover fornece dados municipais no zoom intermediário e zonais no zoom
   máximo, sem desenhar linhas internas.
3. Não há traços brancos nas setas; o modo preenchido não contém setas.
4. O zoom e clique do Atlas principal permanecem funcionando como antes.

## Hotfix Atlas principal: preservar zoom ao navegar entre páginas

Após a aprovação visual de **Deltas e viradas**, foi relatada uma nova
regressão de clique/zoom da página principal. A página de deltas e seu
renderer NÃO foram alterados.

O Atlas agora tem dois caminhos complementares para focar a cidade:

- **Leaflet:** `CityFocus` executa `fitBounds` imediatamente no clique.
- **Servidor:** `municipal_focus_bounds(geometry, codigo_ibge)` utiliza
  exatamente o polígono municipal já exibido para definir os limites
  iniciais do mapa no rerun. Isso impede que uma remontagem do componente
  devolva a câmera ao mapa nacional.
- O componente informa somente `last_clicked`, `last_object_clicked` e
  `last_object_clicked_count`; zoom, centro e arrasto nunca provocam
  reruns. A seleção escolhe o evento **que mudou**, evitando reutilizar
  coordenadas antigas guardadas pelo `streamlit-folium`.
- Caso o callback ocorra após a construção do mapa, um único `st.rerun()`
  adicional aplica o novo foco. A checagem de mudança impede loops.
- `CityFocus` recebe `home_bounds` separadamente para que o botão
  **Voltar ao mapa completo** e Esc não usem erroneamente o limite da
  cidade como enquadramento original.
- Testes novos cobrem cálculo de bounds por código IBGE, clique de
  Canvas, eventos antigos e repetidos, ausência de zoom entre os dados
  retornados e manutenção dos bounds originais.

### Procedimento obrigatório de validação local

Com o processo Streamlit anterior encerrado (`Ctrl+C`):

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

No navegador, conferir o comportamento do Atlas principal na ordem:

1. Em **Automático**, clicar no município e observar enquadramento
   imediato, foco, tooltip e carregamento de detalhes.
2. Usar Esc ou **Voltar ao mapa completo**; o limite inicial da UF/Brasil
   precisa ser restaurado.
3. Repetir o clique no mesmo município e, depois, em outro município.
4. Aproximar/arrastar sem clique: o Streamlit não deve desmontar o mapa.
5. Navegar para **Deltas e viradas**, voltar ao **Atlas Eleitoral** e
   repetir o clique. Validar as duas páginas separadamente.

O teste de unidade é necessário, mas **não substitui** a verificação do
browser com os Parquets locais. Não fazer merge até o operador confirmar
o resultado. A causa exata do problema intermitente não foi reproduzida
no navegador durante esta revisão; as alterações protegem contra as
rotas de rerun e de evento obsoleto identificadas no código.

## Atlas principal — navegação unificada por zoom, clique e seletores

Revisão solicitada após o relato de que a opção manual **Zona eleitoral
(aproximada)** impedia o zoom esperado. A página `Deltas e viradas`
está aprovada e **não foi modificada** nesta revisão.

### Fluxo único

- **Removido** o painel de radio `Detalhamento geográfico`. A interface do
  Atlas usa internamente apenas `level = "Automático"` e a camada
  municipal do IBGE como base, preservando a visualização de votação.
- Clique no polígono municipal faz foco, escurece o contexto e define a câmera
  no centro do município, com **zoom mínimo 10** (`ZONE_ZOOM`). Municípios
  extensos deixam de parar em zoom 7/8, no qual a camada zonal fica oculta.
- Município escolhido no **seletor** recebe a mesma lógica de `CityFocus`
  (incluindo zoom zonal mínimo e fundo escurecido), sem depender de uma
  opção de detalhamento manual.
- A camada de zonas aproximadas para a cidade em foco é montada na árvore
  base do Folium, não em um grupo dinâmico adicionado posteriormente pelo
  `streamlit-folium`. Isso permite que o pane
  `atlasZonasCidade` siga o zoom do Leaflet.
- Seleção de cidade tem prioridade sobre o carregamento indiscriminado de
  uma UF: mesmo nas UFs com mais de 900 zonas, as zonas do município
  clicado não são eliminadas pelo limite da camada.
- Em zoom `ZONE_ZOOM=10`, áreas aproximadas de zona aparecem, quando
  disponíveis. Em `SITE_ZOOM=12`, os locais oficiais podem aparecer, caso
  a preparação de seções/locais tenha sido feita.
- **UF, Município e Zona** permanecem selecionáveis e pesquisáveis na
  barra lateral. Filtrar uma zona usa seus votos reais e não a apresenta
  como perímetro legal/oficial.
- Quando o arquivo `data/geo/zonas/zonas_municipio_UF.geojson` não está
  preparado, o Atlas não inventa zonas: mantém mapa municipal e informa
  a indisponibilidade no caption.

### Teste local obrigatório

Encerre o processo atual do Streamlit (`Ctrl+C`) e, na branch do PR:

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

Verifique o caso da captura com **UF=Todas**, clique em **Rio Verde**,
confirme foco/escurecimento/zoom >=10 e visualização das zonas se a
geometria de GO estiver preparada. Repita via seletor de Município e
Zona; confirme a retirada do painel de detalhamento. Ao aproximar
mais, conferir locais se disponíveis. Verifique também **Voltar/Esc**.

A visualização com os Parquets reais e o navegador ainda precisa de
aceitação antes do merge do PR #11.

## Modos mutuamente excludentes, divisas e clique para ampliar (revisão)

O controle anterior (`folium.LayerControl` com dois overlays) usava
checkboxes e permitia dois modos simultâneos ou nenhum modo. Agora existe
um controle Leaflet com **radios exclusivos** (`Divisões + setas` e
`Áreas por delta (sem setas)`). O OpenStreetMap permanece como mapa-base.

| Zoom | Divisões no modo preenchido | Comportamento do clique |
| --- | --- | --- |
| 0–6 | Estados | Clique numa UF: enquadra e aproxima até municípios (zoom mínimo 7) |
| 7–10 | Municípios, mais limites estaduais | Clique num município: enquadra e aproxima ao zoom das zonas (mínimo 11) |
| 11+ | Zonas aproximadas quando preparadas; senão municípios | Clique em zona: amplia/destaca a área selecionada |

As divisas do modo preenchido são **finas e escuras**, para evitar
reintroduzir os riscos brancos vistos antes. A região selecionada
recebe somente um contorno de foco discreto. O modo `Divisões + setas`
continua sem divisas internas por padrão, com somente a borda estadual
e a região clicada em destaque. As setas seguem o desenho de Canvas em
vermelho/azul, **sem contorno branco**.

O zoom e a troca dos radios acontecem diretamente no Leaflet e **não
enviam eventos ao Streamlit**. `← Voltar ao mapa completo` ou `Esc`
recuperam o enquadramento original. Tooltips e valores eleitorais
continuam inalterados.

**Limite conhecido:** quando a página está em `UF=Todas`, a malha
zonal nacional não é pré-carregada. Assim, o clique municipal aproxima,
mas o último nível fica municipal até selecionar uma UF cujo arquivo
de zonas aproximadas já esteja preparado.

Nesta revisão apenas o módulo `mapa_eleicoes/swing_layers.py`,
seus testes e a documentação de deltas foram alterados. Não foi
modificado nenhum arquivo da página principal do Atlas nem o cálculo
matemático das diferenças de votos.

### Checagem pelo Makefile

```powershell
git fetch origin
git merge --ff-only origin/feature/deltas-viradas-municipio-zona-20261027
make test
make preview ANO=2026
```

Testar os dois radios, contornos do modo preenchido e cliques nas
transições de zoom 6→7→11. Verificar o `Esc`/`Voltar` e, em outra aba
ou página, se o clique e o foco do **Atlas Eleitoral principal** seguem
normais. A PR permanece draft até essa validação no Windows.

## Correção de responsividade — zoom e pan sem travamento

Após o primeiro teste no navegador do controle de radios exclusivos, o
usuário observou travamento e impossibilidade de **arrastar o mapa**
ao dar zoom. A hipótese técnica identificada no JavaScript era uma
interferência de processamento entre o evento de deslocamento do Leaflet,
a reaplicação dos estilos da malha e o desenho síncrono das setas.

O mapa de **Deltas e viradas** passou a separar esses eventos:

- `zoomend` → `sync()`: altera a escala territorial e reaplica o estilo
  das geometrias **somente quando modo, nível ou foco mudam**.
- `moveend` e `resize` → `scheduleRedraw()`: apenas atualizam o
  Canvas de setas após o pan/resize, **sem** reestilizar municípios/zonas,
  recalcular limites ou modificar o centro/zoom.
- `L.Util.requestAnimFrame()` consolida redesenhos concorrentes em um
  quadro; o Canvas continua com `pointer-events:none`.
- O click dos polígonos não usa mais `stopPropagation` no evento nativo,
  evitando interferência com o `drag`. A navegação por clique só ocorre
  quando `map.dragging.moved()` não indicou um arrasto.
- A paleta eleitoral, os radios exclusivos, as divisões no modo
  preenchido, tooltips, `Esc` e Voltar foram preservados.
- **Escopo:** somente `mapa_eleicoes/swing_layers.py`, seu teste e
  esta documentação. O Atlas principal não sofreu modificações.

### Checagem de aceitação

Com o servidor anterior encerrado, atualizar a branch pelo Git/Makefile
e executar `make test`, depois `make preview ANO=2026`.
No navegador, repetir pelo menos: clicar em uma UF, aproximar e arrastar
livremente; rolar o zoom várias vezes; alternar os dois radios e arrastar;
clicar em município/zona e repetir o pan; testar Esc/Voltar.
Verificar que os tooltips ainda acompanham a região sob o cursor e que
nenhum deslocamento comum provoca novo foco ou retorno da câmera.

**Validação ainda pendente** com os dados locais e o Firefox/Chromium do
usuário; o teste estático de eventos não substitui esta validação visual.
