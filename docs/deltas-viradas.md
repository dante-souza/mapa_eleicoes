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
