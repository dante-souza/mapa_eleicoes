import polars as pl
import pytest
from mapa_eleicoes.swing import swing_results, state_swing_results

def sample():
    rows=[]
    for city,zone,records in [
        ("100",1,[(1,"13",40),(1,"22",60),(2,"13",80),(2,"22",70)]),
        ("200",3,[(1,"13",100),(1,"22",20),(2,"13",110),(2,"22",40)])]:
        for turn,num,n in records:
            rows.append(dict(uf="SP",cd_municipio_tse=city,municipio="City "+city,
                             zona=zone,turno=turn,numero=num,tipo_voto="nominal",votos=n))
    return pl.DataFrame(rows)

def test_delta_and_flip():
    a,b=swing_results(sample()).sort("cd_municipio_tse").to_dicts()
    assert (a["saldo_1t"],a["saldo_2t"],a["delta"])==(-20,10,30)
    assert a["delta"]==a["delta_a"]-a["delta_b"]
    assert a["virada"]=="Para A"
    assert b["delta"]==-10 and b["virada"]=="Sem virada"

def test_zones():
    assert swing_results(sample(),level="zona").height==2

def test_missing_round_is_not_zero():
    frame=sample().filter(~((pl.col("cd_municipio_tse")=="200")&(pl.col("turno")==2)))
    assert swing_results(frame).height==1
    with pytest.raises(ValueError):
        swing_results(sample().filter(pl.col("turno")==1))


def test_state_delta_sums_balances_not_majority_of_municipal_arrows():
    # Dois municípios comparáveis na mesma UF; ambos precisam contribuir
    # com seus votos/saldos, independentemente do sentido individual.
    state = state_swing_results(swing_results(sample()))
    assert state.height == 1
    record = state.to_dicts()[0]
    assert record["uf"] == "SP"
    assert record["saldo_1t"] == (-20 + 80)
    assert record["saldo_2t"] == (10 + 70)
    assert record["delta"] == 20
    assert record["delta"] == record["delta_a"] - record["delta_b"]
    assert record["municipios_comparaveis"] == 2
    assert record["virada"] == "Sem virada"


def test_no_fabricated_state_on_empty_frame():
    assert state_swing_results(pl.DataFrame()).is_empty()
