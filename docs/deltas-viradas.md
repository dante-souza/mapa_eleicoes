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
