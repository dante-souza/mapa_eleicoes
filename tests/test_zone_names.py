"""Nome aproximado da zona: bairro / municipio com mais secoes."""
from __future__ import annotations

import polars as pl

from mapa_eleicoes.zone_names import zone_label, zone_labels


def locations():
    rows = [
        # zona 1 em SP: 2 secoes na VILA MARIANA, 1 no IPIRANGA
        ("SP", "71072", 1, 1, 1, "VILA MARIANA"),
        ("SP", "71072", 1, 2, 1, "VILA MARIANA"),
        ("SP", "71072", 1, 3, 1, "IPIRANGA"),
        # 2o turno repete as mesmas secoes: nao pode dobrar o peso
        ("SP", "71072", 1, 3, 2, "IPIRANGA"),
        ("SP", "71072", 1, 3, 2, "IPIRANGA"),
        # zona 5 abrange dois municipios: 2 secoes em 62910, 1 em 61000
        ("SP", "62910", 5, 10, 1, ""),
        ("SP", "62910", 5, 11, 1, ""),
        ("SP", "61000", 5, 12, 1, "CENTRO"),
    ]
    return pl.DataFrame(rows, orient="row",
                        schema=["uf", "cd_municipio_tse", "zona", "secao", "turno", "bairro"])


def test_neighborhood_and_seat_by_sections():
    neighborhood, seat = zone_labels(locations())
    assert neighborhood["SP:71072:1"] == "VILA MARIANA"
    assert seat["SP:5"] == "62910" and seat["SP:1"] == "71072"
    # bairro vazio nunca vira nome
    assert "SP:62910:5" not in neighborhood


def test_label_prefers_neighborhood_then_seat_city():
    labels = zone_labels(locations())
    names = {"SP:62910": "CAMPINAS", "SP:71072": "SÃO PAULO"}
    assert zone_label("SP", 1, "71072", *labels, names) == "VILA MARIANA"
    assert zone_label("SP", 5, None, *labels, names) == "CAMPINAS"
    assert zone_label("SP", 5, "62910", *labels, names) == "CAMPINAS"
    assert zone_label("SP", 99, None, *labels, names) == ""
    # arquivo antigo sem coluna bairro: so o municipio principal
    neighborhood, seat = zone_labels(locations().drop("bairro"))
    assert neighborhood == {} and seat["SP:5"] == "62910"


def test_polling_location_keeps_neighborhood_when_present():
    from mapa_eleicoes.polling_locations import normalize_location
    row = {"SG_UF": "SP", "CD_MUNICIPIO": "71072", "NR_ZONA": "6", "NR_SECAO": "10",
           "NR_TURNO": "1", "NR_LATITUDE": "-23,58", "NR_LONGITUDE": "-46,63",
           "NM_BAIRRO": " VILA MARIANA "}
    assert normalize_location(row)["bairro"] == "VILA MARIANA"
    row.pop("NM_BAIRRO")
    assert normalize_location(row)["bairro"] == ""
