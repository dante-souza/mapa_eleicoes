"""Fontes geograficas oficiais para o Atlas Eleitoral.

Entrada operacional exclusiva: Makefile (make geo-setup / make geo-check).
Dados de referencia sao locais, cacheados e ignorados pelo Git.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import geopandas as gpd
import polars as pl

from mapa_eleicoes import cli
from mapa_eleicoes.geo_bridge import ibge_code

DATA = cli.DATA
TSE_CROSSWALK_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/"
    "municipio_tse_ibge/municipio_tse_ibge.zip"
)
IBGE_MUNICIPAL_URL = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/"
    "malhas_territoriais/malhas_municipais/municipio_{year}/"
    "Brasil/BR_Municipios_{year}.zip"
)
IBGE_CODE_COLUMNS = (
    "CD_MUN", "CD_GEOCMU", "CD_MUN_IBGE",
    "codigo_ibge", "code_muni", "codarea",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_zip(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist():
                raise ValueError(f"ZIP sem membros: {path}")
            # O diretorio central basta para conferência inicial; CRC total
            # de um shapefile nacional de 226 MB seria muito custoso no cache.
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Arquivo ZIP invalido: {path}") from exc


def download(url: str, destination: Path) -> Path:
    """Download atomico de URL oficial com reutilizacao de ZIP verificado."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        verify_zip(destination)
        print(f"[GEO CACHE] {destination} ({destination.stat().st_size:,} bytes)")
        return destination
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        request = Request(url, headers={"User-Agent": "MapaEleicoes/geo-setup/0.3"})
        with urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
        verify_zip(temporary)
        os.replace(temporary, destination)
    except Exception as exc:
        raise RuntimeError(
            f"Falha no download oficial: {url}\n"
            f"Origem pode estar temporariamente indisponivel. "
            f"Baixe pelo navegador e forneca MALHA=... ou CROSSWALK=... ao make geo-setup."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[GEO DOWNLOAD] {destination} ({destination.stat().st_size:,} bytes)")
    return destination


def _shapefile_source(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".zip":
        verify_zip(path)
        return f"zip://{path.resolve().as_posix()}"
    return str(path.resolve())


def build_municipal_geojson(
    source: Path,
    target: Path,
    *,
    simplify_meters: int = 1000,
) -> dict:
    """Poligonos do IBGE simplificados em metros e chave em texto de 7 digitos.

    Nao usa merge com Polars nem projeta zona eleitoral sobre municipio.
    """
    if simplify_meters < 0 or simplify_meters > 10000:
        raise ValueError("simplify_meters deve estar entre 0 e 10000")
    source_uri = _shapefile_source(source)
    print(f"[GEO] Lendo malha municipal: {source}")
    geometry = gpd.read_file(source_uri)
    if geometry.empty:
        raise ValueError("Malha do IBGE sem feicoes")
    if geometry.crs is None:
        raise ValueError("Malha do IBGE nao informa o CRS")
    code_column = next(
        (column for column in IBGE_CODE_COLUMNS if column in geometry.columns),
        None,
    )
    if code_column is None:
        raise ValueError(
            "Nao encontrei codigo IBGE municipal. Colunas: "
            + ", ".join(str(c) for c in geometry.columns)
        )
    # Normaliza para um contrato minimo e imutavel para app.py.
    codes = [ibge_code(value) for value in geometry[code_column]]
    if any(len(code) != 7 for code in codes):
        raise ValueError("Malha contem geocodigos municipais vazios/invalidos")
    if len(set(codes)) != len(codes):
        raise ValueError("Malha contem geocodigos municipais duplicados")
    base = geometry[["geometry"]].copy()
    base["codigo_ibge"] = codes
    base = base.loc[base.geometry.notna() & ~base.geometry.is_empty].copy()
    if base.empty:
        raise ValueError("Malha sem geometrias aproveitaveis")
    # EPSG:3857 usa metros; evita simplificar por graus (distorcao espacial).
    base = base.to_crs("EPSG:3857")
    if simplify_meters:
        base["geometry"] = base.geometry.simplify(
            simplify_meters, preserve_topology=True
        )
    base = base.to_crs("EPSG:4326")
    base = base.loc[base.geometry.notna() & ~base.geometry.is_empty].copy()
    if base.empty:
        raise ValueError("Simplificacao removeu todas as geometrias")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".part.geojson")
    try:
        base.to_file(tmp, driver="GeoJSON", index=False)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    meta = {
        "arquivo": str(target),
        "municipios": len(base),
        "fonte_coluna": code_column,
        "crs": "EPSG:4326",
        "simplificacao_metros_mercator": simplify_meters,
        "source_sha256": cli.hash_file(source),
        "data_utc": utc_now(),
    }
    print(f"[GEO OK] {len(base):,} feicoes em {target}")
    return meta


def setup(
    year: int = 2025,
    *,
    crosswalk: Path | None = None,
    malha: Path | None = None,
    simplify_meters: int = 1000,
    force: bool = False,
) -> dict:
    """Instala a malha IBGE e o de/para TSE, sem redescarregar arquivos cacheados."""
    if year < 2000 or year > 2100:
        raise ValueError("Ano de malha invalido")
    refs = DATA / "reference"
    geo = DATA / "geo"
    local_crosswalk = crosswalk or (
        refs / "source" / "municipio_tse_ibge.zip"
    )
    local_malha = malha or (
        geo / "source" / f"BR_Municipios_{year}.zip"
    )
    results: dict = {
        "ano_malha_ibge": year,
        "fonte_ibge": IBGE_MUNICIPAL_URL.format(year=year),
        "fonte_tse": TSE_CROSSWALK_URL,
        "data_utc": utc_now(),
    }
    target_ref = refs / "tse_ibge.csv"
    target_geo = geo / "municipios.geojson"
    if force or not target_ref.is_file():
        if crosswalk is None:
            download(TSE_CROSSWALK_URL, local_crosswalk)
        print(f"[GEO] Normalizando correspondencia TSE/IBGE: {local_crosswalk}")
        # cli.crosswalk_import usa exclusivamente Polars; nenhum pandas explicito.
        cli.crosswalk_import(local_crosswalk)
    if not target_ref.is_file():
        raise FileNotFoundError(target_ref)
    references = pl.read_csv(target_ref, infer_schema=False)
    results["de_para"] = {
        "linhas": references.height,
        "fonte_sha256": cli.hash_file(local_crosswalk) if local_crosswalk.is_file() else None,
    }
    if force or not target_geo.is_file():
        if malha is None:
            download(IBGE_MUNICIPAL_URL.format(year=year), local_malha)
        results["geometria"] = build_municipal_geojson(
            local_malha, target_geo, simplify_meters=simplify_meters
        )
    if not target_geo.is_file():
        raise FileNotFoundError(target_geo)
    geometry = gpd.read_file(target_geo)
    results["geometrias_disponiveis"] = len(geometry)
    geo.mkdir(parents=True, exist_ok=True)
    manifest = geo / "official_sources.json"
    manifest.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[GEO SETUP] de/para: {references.height:,}; "
          f"geometrias: {len(geometry):,}; metadata: {manifest}")
    return results


def coverage(election_year: int = 2026) -> dict:
    """Checa cobertura por codigo, sem supor que votos BR ou PR estao completos."""
    ref_path = DATA / "reference" / "tse_ibge.csv"
    geo_path = DATA / "geo" / "municipios.geojson"
    if not ref_path.is_file() or not geo_path.is_file():
        raise FileNotFoundError(
            "Geografia incompleta. Execute make geo-setup antes de make geo-check."
        )
    refs = pl.read_csv(ref_path, infer_schema=False).select(
        ["uf", "cd_municipio_tse", "codigo_ibge"]
    ).unique()
    collisions = (
        refs.group_by(["uf", "cd_municipio_tse"]).len()
        .filter(pl.col("len") > 1)
    )
    if not collisions.is_empty():
        raise ValueError("De/para ambiguo: varios codigos IBGE para mesma chave TSE")
    geometry = gpd.read_file(geo_path)
    if "codigo_ibge" not in geometry.columns:
        raise ValueError("Malha importada sem codigo_ibge")
    existing = {ibge_code(value) for value in geometry["codigo_ibge"]}
    if not existing:
        raise ValueError("Malha sem codigos IBGE")
    paths = sorted((DATA / "processed" / str(election_year)).glob("votos_*.csv.gz"))
    if not paths:
        raise FileNotFoundError(
            f"Sem votos processados de {election_year}; execute make prepare-data."
        )
    keys: list[pl.DataFrame] = []
    for path in paths:
        with gzip.open(path, "rb") as stream:
            frame = pl.read_csv(
                stream, columns=["uf", "cd_municipio_tse"], infer_schema=False
            )
        keys.append(frame.unique())
    votes = pl.concat(keys, how="vertical").unique()
    matches = votes.join(refs, on=["uf", "cd_municipio_tse"], how="left", validate="m:1")
    unmapped = matches.filter(pl.col("codigo_ibge").is_null())
    unknown_geo = matches.filter(
        pl.col("codigo_ibge").is_not_null()
        & ~pl.col("codigo_ibge").is_in(sorted(existing))
    )
    summary = {
        "ano_eleitoral": election_year,
        "total_chaves_tse": matches.height,
        "nao_mapeadas_tse_ibge": unmapped.height,
        "sem_poligono_ibge": unknown_geo.height,
        "poligonos_disponiveis": len(existing),
        "exemplos_sem_de_para": unmapped.head(10).to_dicts(),
        "exemplos_sem_poligono": unknown_geo.head(10).to_dicts(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Geografia oficial; usar Makefile")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("setup")
    make.add_argument("--geo-year", type=int, default=2025)
    make.add_argument("--crosswalk", type=Path, default=None)
    make.add_argument("--malha", type=Path, default=None)
    make.add_argument("--simplify-meters", type=int, default=1000)
    make.add_argument("--force", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--year", type=int, default=2026)
    args = parser.parse_args(argv)
    if args.command == "setup":
        setup(
            args.geo_year, crosswalk=args.crosswalk, malha=args.malha,
            simplify_meters=args.simplify_meters, force=args.force,
        )
    else:
        coverage(args.year)


if __name__ == "__main__":
    main()
