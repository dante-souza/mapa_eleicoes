"""Areas aproximadas de zona: setores IBGE 2022 + locais de votacao TSE."""
from __future__ import annotations

import json
import zipfile

import geopandas as gpd
import polars as pl
import pytest
from shapely.geometry import box

from mapa_eleicoes import zone_geometry as zg

SP = "3550308"      # IBGE Sao Paulo
OTHER = "3509502"   # IBGE Campinas (sem locais neste teste)
# Grade 2x2 de setores em SP; um setor isolado no outro municipio.
TRACTS = {
    "355030800000001": (SP, box(-46.70, -23.60, -46.65, -23.55)),
    "355030800000002": (SP, box(-46.65, -23.60, -46.60, -23.55)),
    "355030800000003": (SP, box(-46.70, -23.65, -46.65, -23.60)),
    "355030800000004": (SP, box(-46.65, -23.65, -46.60, -23.60)),
    "350950200000001": (OTHER, box(-47.10, -22.95, -47.05, -22.90)),
}


def write_tracts(folder):
    gdf = gpd.GeoDataFrame(
        {
            "CD_SETOR": list(TRACTS),
            "CD_MUN": [mun for mun, _ in TRACTS.values()],
            "CD_UF": ["35"] * len(TRACTS),
        },
        geometry=[geom for _, geom in TRACTS.values()],
        crs="EPSG:4674",
    )
    shp = folder / "SP_setores_CD2022.shp"
    gdf.to_file(shp)
    archive = folder / "SP_setores_CD2022.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for part in folder.glob("SP_setores_CD2022.*"):
            if part.suffix != ".zip":
                zf.write(part, part.name)
    return archive


def section(zona, secao, lat, lon, turno=1, mun="71072"):
    return {"uf": "SP", "cd_municipio_tse": mun, "zona": zona, "secao": secao,
            "turno": turno, "local": "1", "nome_local": "", "endereco": "",
            "latitude": lat, "longitude": lon}


def locations():
    rows = [
        # Setor 1: 3 secoes da zona 1 e 1 da zona 2 -> zona 1.
        section(1, 1, -23.575, -46.675), section(1, 2, -23.575, -46.675),
        section(1, 3, -23.575, -46.675), section(2, 4, -23.576, -46.676),
        # Mesmas secoes no 2o turno nao podem dobrar o peso.
        section(2, 4, -23.576, -46.676, turno=2),
        section(2, 4, -23.576, -46.676, turno=2),
        # Setor 2: zona 2.
        section(2, 5, -23.575, -46.625),
        # Setor 3: empate 1 x 1 -> menor numero de zona.
        section(1, 6, -23.625, -46.675), section(2, 7, -23.626, -46.676),
        # Setor 4: sem local -> proximidade (local mais proximo e o do setor 2).
        # Local declarado em SP mas com ponto em Campinas: descartado.
        section(3, 8, -22.925, -47.075),
    ]
    frame = pl.DataFrame(rows).with_columns(
        pl.col("zona").cast(pl.Int32), pl.col("secao").cast(pl.Int32),
        pl.col("turno").cast(pl.Int16),
    )
    return frame


def crosswalk():
    return pl.DataFrame({
        "uf": ["SP", "SP"], "cd_municipio_tse": ["71072", "62910"],
        "codigo_ibge": [SP, OTHER],
    })


def test_section_weights_ignore_second_round_duplicates():
    places = zg.place_weights(locations(), crosswalk())
    zone2_setor1 = places.filter(
        (pl.col("zona") == 2) & (pl.col("latitude") == -23.576)
    )
    assert zone2_setor1["n_secoes"].to_list() == [1]


def test_dominant_zone_tie_proximity_and_wrong_municipality(tmp_path):
    tracts = zg.read_tracts(write_tracts(tmp_path), uf="SP")
    assert set(tracts["codigo_ibge"]) == {SP, OTHER}
    places = zg.place_weights(locations(), crosswalk())
    assignments, report = zg.assign_tracts(tracts, places)
    zone_of = dict(zip(assignments["cd_setor"], assignments["zona"]))
    how = dict(zip(assignments["cd_setor"], assignments["criterio"]))
    assert zone_of["355030800000001"] == 1
    assert zone_of["355030800000002"] == 2
    assert zone_of["355030800000003"] == 1 and report["setores_empate"] == 1
    assert how["355030800000004"] == "proximidade"
    # Ponto declarado em Sao Paulo, mas dentro de Campinas: descartado.
    assert report["locais_fora_do_municipio"] == 1
    # Campinas nao tem local valido: sem area de zona, nada inventado.
    assert "350950200000001" not in zone_of
    assert report["municipios_sem_locais"] == 1


def test_dissolve_produces_labeled_approximate_zone_areas(tmp_path):
    tracts = zg.read_tracts(write_tracts(tmp_path), uf="SP")
    assignments, _ = zg.assign_tracts(tracts, zg.place_weights(locations(), crosswalk()))
    zones = zg.dissolve_zones(tracts, assignments, simplify_meters=10)
    assert sorted(zones["map_id"]) == ["SP:71072:1", "SP:71072:2"]
    assert set(zones["n_zonas_municipio"]) == {2}
    assert all(zones["aproximada"]) and set(zones["metodo"]) == {zg.METHOD}
    assert zones.crs.to_epsg() == 4326
    # As duas areas cobrem o municipio sem sobreposicao relevante.
    metric = zones.to_crs(zg.METRIC_CRS)
    union_area = metric.union_all().area
    city_area = tracts.loc[tracts["codigo_ibge"] == SP].union_all().area
    assert union_area == pytest.approx(city_area, rel=0.01)
    assert metric.area.sum() == pytest.approx(union_area, rel=0.01)


def test_setup_writes_per_uf_geojson_and_manifest(tmp_path):
    root = tmp_path / "data"
    (root / "serving" / "2026").mkdir(parents=True)
    (root / "reference").mkdir(parents=True)
    locations().write_parquet(root / "serving" / "2026" / "locais.parquet")
    crosswalk().write_csv(root / "reference" / "tse_ibge.csv")
    source = tmp_path / "src"
    source.mkdir()
    manifest = zg.setup(2026, ["SP"], setores=write_tracts(source), root=root)
    output = zg.zone_file(root, "SP")
    assert output.is_file()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert {f["properties"]["map_id"] for f in data["features"]} == {"SP:71072:1", "SP:71072:2"}
    assert manifest["aproximada"] is True
    assert manifest["ufs"]["SP"]["fonte_setores"]["sha256"]
    assert (root / "geo" / "zonas" / "manifest.json").is_file()
    with pytest.raises(ValueError):
        zg.setup(2026, ["XX"], setores=write_tracts(source), root=root)
