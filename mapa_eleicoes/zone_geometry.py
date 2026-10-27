"""Area APROXIMADA de zona eleitoral dentro do municipio (metodo C).

Nao existe malha oficial de zonas eleitorais. Este modulo DERIVA uma area
aproximada a partir de duas fontes oficiais, sem nomes nem centroides:

1. Malha de setores censitarios do Censo 2022 (IBGE), que se aninha nos
   municipios (CD_MUN = 7 primeiros digitos de CD_SETOR).
2. Coordenadas dos locais de votacao do TSE (`locais.parquet`), com
   uf + municipio TSE + zona + secao.

Cada setor recebe a zona que tem MAIS SECOES em locais de votacao dentro
dele. Setor sem local de votacao recebe a zona do local mais proximo do
MESMO municipio. Setores sao entao unidos de duas formas:

- por (uf, municipio TSE, zona): zonas DENTRO da cidade (zonas_municipio_UF);
- por (uf, zona): a zona inteira, que no interior costuma abranger varios
  municipios (zonas_uf_UF), base do mapa "por zona eleitoral".

Municipio sem local georreferenciado nao recebe area de zona (ausencia).

O resultado e sempre rotulado como aproximado e registra metodo, fontes,
hashes e contagens no manifesto. Polars faz contagens e pesos; GeoPandas
apenas geometria. A fronteira entre os dois usa listas de escalares.

Uso exclusivo via Makefile: make zones-setup.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import polars as pl
import shapely
from shapely.geometry import Point

from mapa_eleicoes import cli
from mapa_eleicoes.geo_bridge import ibge_code
from mapa_eleicoes.geography import download, verify_zip

DATA = cli.DATA
REVISION = 2
METHOD = "setores_ibge_2022_zona_dominante_por_secoes"
METRIC_CRS = "EPSG:5880"  # SIRGAS 2000 / Brazil Polyconic (metros)
SETORES_BASE = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
    "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/setores/shp/"
)
SETORES_UF_URL = SETORES_BASE + "UF/{uf}_setores_CD2022.zip"
SETORES_BR_URL = SETORES_BASE + "BR/BR_setores_CD2022.zip"
UF_PREFIX = {uf: prefix for prefix, uf in cli.IBGE_UF_BY_PREFIX.items()}
ZONE_KEYS = ["uf", "cd_municipio_tse", "zona"]


def zone_area_id(uf: object, cd_municipio_tse: object, zona: object) -> str:
    """Chave da area de zona dentro do municipio: 'SP:71072:1'."""
    return f"{str(uf).strip().upper()}:{str(cd_municipio_tse).strip()}:{int(zona)}"


def read_tracts(source: Path, uf: str | None = None) -> gpd.GeoDataFrame:
    """Setores IBGE 2022 (cd_setor, codigo_ibge, geometria) em CRS metrico."""
    path = source
    if source.suffix.lower() == ".zip":
        verify_zip(source)
        path = f"zip://{source.resolve().as_posix()}"
    columns = ["CD_SETOR", "CD_MUN"]
    kwargs = {}
    if uf is not None:
        # O filtro precisa estar entre as colunas lidas (pyogrio devolve
        # zero feicoes se o campo do WHERE nao for selecionado).
        columns.append("CD_UF")
        kwargs["where"] = f"CD_UF = '{UF_PREFIX[uf]}'"
    tracts = gpd.read_file(path, columns=columns, **kwargs)
    if tracts.crs is None:
        raise ValueError("Malha de setores sem CRS")
    if not {"CD_SETOR", "CD_MUN"} <= set(tracts.columns):
        raise ValueError("Malha de setores sem CD_SETOR/CD_MUN")
    tracts = tracts.loc[tracts.geometry.notna()].copy()
    tracts["cd_setor"] = [str(value).strip() for value in tracts["CD_SETOR"]]
    tracts["codigo_ibge"] = [ibge_code(value) for value in tracts["CD_MUN"]]
    tracts = tracts.loc[tracts["codigo_ibge"] != ""]
    return tracts[["cd_setor", "codigo_ibge", "geometry"]].to_crs(METRIC_CRS)


def place_weights(locations: pl.DataFrame, crosswalk: pl.DataFrame) -> pl.DataFrame:
    """Locais de votacao com peso = numero de secoes distintas.

    Secao e a mesma nos dois turnos: deduplica por (uf, municipio, zona,
    secao) antes de pesar, sem somar turnos.
    """
    needed = {"uf", "cd_municipio_tse", "zona", "secao", "latitude", "longitude"}
    if locations.is_empty() or not needed <= set(locations.columns):
        return pl.DataFrame()
    sections = locations.unique(
        subset=["uf", "cd_municipio_tse", "zona", "secao"], keep="first"
    )
    places = (
        sections.group_by(["uf", "cd_municipio_tse", "zona", "latitude", "longitude"])
        .agg(pl.col("secao").n_unique().alias("n_secoes"))
    )
    keys = crosswalk.select(["uf", "cd_municipio_tse", "codigo_ibge"]).unique()
    return places.join(keys, on=["uf", "cd_municipio_tse"], how="inner", validate="m:1")


def _points(places: pl.DataFrame) -> gpd.GeoDataFrame:
    """Locais como pontos GeoPandas a partir de escalares Python."""
    rows = list(places.iter_rows(named=True))
    return gpd.GeoDataFrame(
        {
            "codigo_ibge": [row["codigo_ibge"] for row in rows],
            "uf": [row["uf"] for row in rows],
            "cd_municipio_tse": [row["cd_municipio_tse"] for row in rows],
            "zona": [int(row["zona"]) for row in rows],
            "n_secoes": [int(row["n_secoes"]) for row in rows],
        },
        geometry=[Point(float(row["longitude"]), float(row["latitude"])) for row in rows],
        crs="EPSG:4326",
    ).to_crs(METRIC_CRS)


def assign_tracts(
    tracts: gpd.GeoDataFrame, places: pl.DataFrame,
) -> tuple[pl.DataFrame, dict]:
    """Zona de cada setor: dominante por secoes; senao, local mais proximo.

    Local cujo ponto cai em setor de OUTRO municipio e descartado (erro de
    coordenada ou de codigo), nunca reatribuido.
    """
    report = {"locais": places.height, "locais_fora_do_municipio": 0,
              "setores_empate": 0, "setores_por_locais": 0,
              "setores_por_proximidade": 0, "municipios_sem_locais": 0}
    if places.is_empty() or tracts.empty:
        return pl.DataFrame(), report
    points = _points(places)
    joined = gpd.sjoin(
        points, tracts[["cd_setor", "codigo_ibge", "geometry"]],
        how="inner", predicate="intersects",
        lsuffix="local", rsuffix="setor",
    )
    hits = pl.DataFrame({
        "cd_setor": [str(v) for v in joined["cd_setor"]],
        "municipio_setor": [str(v) for v in joined["codigo_ibge_setor"]],
        "codigo_ibge": [str(v) for v in joined["codigo_ibge_local"]],
        "uf": [str(v) for v in joined["uf"]],
        "cd_municipio_tse": [str(v) for v in joined["cd_municipio_tse"]],
        "zona": [int(v) for v in joined["zona"]],
        "n_secoes": [int(v) for v in joined["n_secoes"]],
        "local_id": [int(v) for v in joined.index],
    }, schema_overrides={"zona": pl.Int32, "n_secoes": pl.Int64})
    # Um ponto na divisa de dois setores conta so no primeiro deles.
    hits = hits.sort(["local_id", "cd_setor"]).unique(
        subset=["local_id"], keep="first", maintain_order=True
    )
    inside = hits.filter(pl.col("municipio_setor") == pl.col("codigo_ibge"))
    report["locais_fora_do_municipio"] = hits.height - inside.height
    weights = (
        inside.group_by(["cd_setor", "codigo_ibge", "uf", "cd_municipio_tse", "zona"])
        .agg(pl.col("n_secoes").sum().alias("peso"))
        .sort(["cd_setor", "peso", "zona"], descending=[False, True, False])
    )
    top = weights.with_columns(
        pl.col("peso").max().over("cd_setor").alias("peso_max"),
        pl.len().over("cd_setor").alias("zonas_no_setor"),
    )
    report["setores_empate"] = (
        top.filter(pl.col("peso") == pl.col("peso_max"))
        .group_by("cd_setor").len().filter(pl.col("len") > 1).height
    )
    dominant = (
        top.unique(subset=["cd_setor"], keep="first", maintain_order=True)
        .select(["cd_setor", "codigo_ibge", "uf", "cd_municipio_tse", "zona"])
        .with_columns(pl.lit("locais").alias("criterio"))
    )
    report["setores_por_locais"] = dominant.height

    # Setores sem local: zona do local valido mais proximo no mesmo municipio.
    valid_ids = set(inside.get_column("local_id").to_list())
    assigned = set(dominant.get_column("cd_setor").to_list())
    points_by_city: dict[str, list[int]] = {}
    for position, (idx, code) in enumerate(zip(points.index, points["codigo_ibge"])):
        if idx in valid_ids:
            points_by_city.setdefault(code, []).append(position)
    pending_by_city: dict[str, list[int]] = {}
    for position, (code, setor) in enumerate(zip(tracts["codigo_ibge"], tracts["cd_setor"])):
        pending_by_city.setdefault(code, [])
        if setor not in assigned:
            pending_by_city[code].append(position)
    nearest_rows: list[dict] = []
    for municipality in sorted(pending_by_city):
        city_points = points_by_city.get(municipality)
        if not city_points:
            report["municipios_sem_locais"] += 1
            continue
        pending = pending_by_city[municipality]
        if not pending:
            continue
        candidates = points.iloc[city_points]
        tree = shapely.STRtree(candidates.geometry.values)
        anchors = tracts.geometry.iloc[pending].representative_point().values
        nearest = tree.nearest(anchors)
        for tract_pos, point_pos in zip(pending, nearest):
            source = candidates.iloc[int(point_pos)]
            nearest_rows.append({
                "cd_setor": str(tracts["cd_setor"].iloc[tract_pos]),
                "codigo_ibge": municipality,
                "uf": str(source["uf"]),
                "cd_municipio_tse": str(source["cd_municipio_tse"]),
                "zona": int(source["zona"]), "criterio": "proximidade",
            })
    report["setores_por_proximidade"] = len(nearest_rows)
    if nearest_rows:
        nearest_frame = pl.DataFrame(nearest_rows).with_columns(
            pl.col("zona").cast(pl.Int32)
        )
        dominant = pl.concat([dominant, nearest_frame], how="vertical")
    return dominant, report


def dissolve_zones(
    tracts: gpd.GeoDataFrame, assignments: pl.DataFrame,
    *, simplify_meters: float = 30.0,
) -> gpd.GeoDataFrame:
    """Une setores por (uf, municipio TSE, zona); simplifica como cobertura.

    coverage_simplify preserva as divisas compartilhadas entre zonas do
    mesmo municipio (sem buracos nem sobreposicoes criados pela simplificacao).
    """
    if assignments.is_empty():
        return gpd.GeoDataFrame(columns=["map_id", "geometry"], geometry="geometry",
                                crs="EPSG:4326")
    by_tract = {row["cd_setor"]: row for row in assignments.iter_rows(named=True)}
    keep = [setor in by_tract for setor in tracts["cd_setor"]]
    base = tracts.loc[keep].copy()
    rows = [by_tract[setor] for setor in base["cd_setor"]]
    base["uf"] = [row["uf"] for row in rows]
    base["cd_municipio_tse"] = [row["cd_municipio_tse"] for row in rows]
    base["zona"] = [int(row["zona"]) for row in rows]
    base["por_proximidade"] = [int(row["criterio"] == "proximidade") for row in rows]
    base["n_setores"] = 1
    zones = base.dissolve(
        by=["uf", "cd_municipio_tse", "codigo_ibge", "zona"],
        aggfunc={"n_setores": "sum", "por_proximidade": "sum"},
        as_index=False,
    )
    zones["geometry"] = shapely.make_valid(zones.geometry.values)
    if simplify_meters:
        simplified = list(zones.geometry.values)
        for code in sorted(set(zones["codigo_ibge"])):
            idx = [i for i, value in enumerate(zones["codigo_ibge"]) if value == code]
            group = shapely.coverage_simplify(
                [simplified[i] for i in idx], simplify_meters
            )
            for i, geometry in zip(idx, group):
                simplified[i] = geometry
        zones["geometry"] = shapely.make_valid(simplified)
    counts = {}
    for code in zones["codigo_ibge"]:
        counts[code] = counts.get(code, 0) + 1
    zones["n_zonas_municipio"] = [counts[code] for code in zones["codigo_ibge"]]
    zones["map_id"] = [
        zone_area_id(uf, tse, zona)
        for uf, tse, zona in zip(zones["uf"], zones["cd_municipio_tse"], zones["zona"])
    ]
    zones["metodo"] = METHOD
    zones["aproximada"] = True
    zones = zones.rename(columns={"por_proximidade": "setores_por_proximidade"})
    return zones[[
        "map_id", "uf", "cd_municipio_tse", "codigo_ibge", "zona",
        "n_zonas_municipio", "n_setores", "setores_por_proximidade",
        "metodo", "aproximada", "geometry",
    ]].to_crs(4326)


def dissolve_districts(
    tracts: gpd.GeoDataFrame, assignments: pl.DataFrame,
    *, simplify_meters: float = 30.0,
) -> gpd.GeoDataFrame:
    """Une setores por (uf, zona): a zona inteira, atravessando municipios.

    Simplificacao como cobertura sobre a UF inteira: divisas entre zonas
    vizinhas (inclusive de municipios diferentes) continuam coincidentes.
    """
    columns = ["map_id", "uf", "zona", "n_municipios", "municipios_tse",
               "n_setores", "setores_por_proximidade", "metodo", "aproximada",
               "geometry"]
    if assignments.is_empty():
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    by_tract = {row["cd_setor"]: row for row in assignments.iter_rows(named=True)}
    base = tracts.loc[[setor in by_tract for setor in tracts["cd_setor"]]].copy()
    rows = [by_tract[setor] for setor in base["cd_setor"]]
    base["uf"] = [row["uf"] for row in rows]
    base["zona"] = [int(row["zona"]) for row in rows]
    base["por_proximidade"] = [int(row["criterio"] == "proximidade") for row in rows]
    base["n_setores"] = 1
    cities: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        cities.setdefault((row["uf"], int(row["zona"])), set()).add(
            str(row["cd_municipio_tse"])
        )
    zones = base[["uf", "zona", "n_setores", "por_proximidade", "geometry"]].dissolve(
        by=["uf", "zona"], aggfunc={"n_setores": "sum", "por_proximidade": "sum"},
        as_index=False,
    )
    zones["geometry"] = shapely.make_valid(zones.geometry.values)
    if simplify_meters and len(zones):
        zones["geometry"] = shapely.make_valid(
            shapely.coverage_simplify(list(zones.geometry.values), simplify_meters)
        )
    members = [sorted(cities[(uf, int(zona))], key=lambda code: (len(code), code))
               for uf, zona in zip(zones["uf"], zones["zona"])]
    zones["n_municipios"] = [len(codes) for codes in members]
    zones["municipios_tse"] = [",".join(codes) for codes in members]
    zones["map_id"] = [f"{uf}:{int(zona)}" for uf, zona in zip(zones["uf"], zones["zona"])]
    zones["metodo"] = METHOD
    zones["aproximada"] = True
    zones = zones.rename(columns={"por_proximidade": "setores_por_proximidade"})
    return zones[columns].to_crs(4326)


def zone_file(root: Path, uf: str) -> Path:
    """Zonas dentro de cada municipio (uf, municipio TSE, zona)."""
    return root / "geo" / "zonas" / f"zonas_municipio_{uf}.geojson"


def district_file(root: Path, uf: str) -> Path:
    """Zona inteira (uf, zona), podendo abranger varios municipios."""
    return root / "geo" / "zonas" / f"zonas_uf_{uf}.geojson"


def _write_geojson(frame: gpd.GeoDataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        frame.to_file(temporary, driver="GeoJSON", index=False)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def build_uf(
    uf: str, setores: Path, locations: pl.DataFrame, crosswalk: pl.DataFrame,
    *, root: Path, simplify_meters: float = 30.0,
) -> dict:
    tracts = read_tracts(setores, uf=uf)
    places = place_weights(locations.filter(pl.col("uf") == uf), crosswalk)
    assignments, report = assign_tracts(tracts, places)
    zones = dissolve_zones(tracts, assignments, simplify_meters=simplify_meters)
    districts = dissolve_districts(tracts, assignments, simplify_meters=simplify_meters)
    target = zone_file(root, uf)
    _write_geojson(zones, target)
    _write_geojson(districts, district_file(root, uf))
    report.update({
        "uf": uf, "setores": len(tracts), "areas_de_zona": len(zones),
        "zonas_completas": len(districts),
        "arquivo_zonas_completas": district_file(root, uf).name,
        "municipios_com_mais_de_uma_zona": len(
            {code for code, n in zip(zones["codigo_ibge"], zones["n_zonas_municipio"]) if n > 1}
        ),
        "arquivo": target.name,
    })
    print(f"[ZONAS] {uf}: {len(zones):,} areas de zona aproximadas a partir de "
          f"{len(tracts):,} setores ({report['setores_por_proximidade']:,} por proximidade)")
    return report


def setup(
    year: int, ufs: list[str] | None = None, *,
    setores: Path | None = None, simplify_meters: float = 30.0,
    root: Path | None = None,
) -> dict:
    data = root or DATA
    locations_path = data / "serving" / str(year) / "locais.parquet"
    crosswalk_path = data / "reference" / "tse_ibge.csv"
    if not locations_path.is_file():
        raise FileNotFoundError(
            f"{locations_path} ausente: prepare os locais de votacao antes das zonas."
        )
    if not crosswalk_path.is_file():
        raise FileNotFoundError(f"{crosswalk_path} ausente: rode a geografia antes.")
    locations = pl.read_parquet(locations_path)
    crosswalk = pl.read_csv(crosswalk_path, infer_schema=False)
    available = sorted(set(locations.get_column("uf").to_list()) & set(UF_PREFIX))
    chosen = [uf.strip().upper() for uf in ufs] if ufs else available
    unknown = sorted(set(chosen) - set(UF_PREFIX))
    if unknown:
        raise ValueError(f"UF invalida para zonas: {unknown}")
    reports, sources = [], {}
    for uf in chosen:
        if setores is not None:
            source, url = setores, None
        else:
            url = SETORES_UF_URL.format(uf=uf)
            source = data / "geo" / "source" / "setores" / f"{uf}_setores_CD2022.zip"
            download(url, source)
        sources[uf] = {
            "arquivo": source.name, "url": url,
            "sha256": cli.hash_file(source), "bytes": source.stat().st_size,
        }
        reports.append(build_uf(
            uf, source, locations, crosswalk,
            root=data, simplify_meters=simplify_meters,
        ))
    manifest_path = data / "geo" / "zonas" / "manifest.json"
    previous = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
    by_uf = previous.get("ufs", {}) if previous.get("revisao") == REVISION else {}
    for report in reports:
        by_uf[report["uf"]] = {**report, "fonte_setores": sources[report["uf"]]}
    manifest = {
        "revisao": REVISION,
        "metodo": METHOD,
        "aproximada": True,
        "descricao": (
            "Area aproximada da zona eleitoral (dentro do municipio e zona "
            "inteira por UF): setores "
            "censitarios IBGE 2022 atribuidos a zona com mais secoes em locais "
            "de votacao TSE no setor; setores sem local recebem a zona do local "
            "mais proximo do mesmo municipio. Nao e limite oficial."
        ),
        "fonte_locais": {"arquivo": locations_path.name,
                         "sha256": cli.hash_file(locations_path)},
        "simplificacao_metros": simplify_meters,
        "ano_eleitoral": year,
        "gerado_utc": datetime.now(timezone.utc).isoformat(),
        "ufs": by_uf,
    }
    temporary = manifest_path.with_suffix(".part.json")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Areas aproximadas de zona eleitoral")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--ufs", default="", help="Ex.: SP,RJ (vazio = UFs dos locais)")
    parser.add_argument("--setores", default="", help="ZIP/SHP/GPKG IBGE 2022 local")
    parser.add_argument("--simplify-meters", type=float, default=30.0)
    args = parser.parse_args(argv)
    ufs = [uf for uf in args.ufs.split(",") if uf.strip()] or None
    setup(
        args.year, ufs,
        setores=Path(args.setores).expanduser() if args.setores else None,
        simplify_meters=args.simplify_meters,
    )


if __name__ == "__main__":
    main()
