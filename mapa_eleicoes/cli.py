"""CLI interna. Execute as tarefas SOMENTE pelos targets do Makefile."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
COLUMNS = [
    'ano', 'turno', 'uf', 'cd_municipio_tse', 'municipio', 'zona',
    'cargo', 'numero', 'candidato', 'tipo_voto', 'votos',
]
INPUT_COLUMNS = {
    'ANO_ELEICAO', 'NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO',
    'NR_ZONA', 'NR_SECAO', 'CD_CARGO', 'DS_CARGO', 'CD_CARGO_PERGUNTA',
    'DS_CARGO_PERGUNTA', 'NR_VOTAVEL', 'NR_CANDIDATO', 'NM_VOTAVEL',
    'NM_URNA_CANDIDATO', 'QT_VOTOS', 'CD_TIPO_VOTAVEL',
    'DS_TIPO_VOTAVEL', 'TP_VOTO', 'SG_PARTIDO',
}
REQUIRED = {'NR_TURNO', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'QT_VOTOS'}


def hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def candidate_csv(zf: zipfile.ZipFile) -> list[str]:
    return [n for n in zf.namelist() if n.lower().endswith('.csv') and not n.startswith('__MACOSX/')]


def ensure_archive(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        with zipfile.ZipFile(path) as z:
            names = candidate_csv(z)
            if not names:
                raise ValueError(f'{path.name}: ZIP sem CSV')
            return names
    except zipfile.BadZipFile as exc:
        raise ValueError(f'{path.name}: ZIP invalido/incompleto — baixe novamente') from exc


def inspect_archive(path: Path) -> dict:
    names = ensure_archive(path)
    result = {'arquivo': path.name, 'bytes': path.stat().st_size, 'csvs': []}
    with zipfile.ZipFile(path) as z:
        for name in names:
            with z.open(name) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding='latin-1', newline=''), delimiter=';')
                header = next(reader)
                first = next(reader, [])
            result['csvs'].append({
                'arquivo': name, 'colunas': header,
                'exemplo': dict(zip(header, first)),
                'bytes_descompactados': z.getinfo(name).file_size,
            })
    return result


def import_archive(file: Path, year: int, raw: Path | None = None) -> Path:
    names = ensure_archive(file)
    if not file.name.lower().endswith('.zip'):
        raise ValueError('Esperado arquivo .zip')
    dest = (raw or DATA / 'raw' / str(year)) / file.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if file.resolve() == dest.resolve():
        return dest
    if dest.exists():
        if hash_file(dest) == hash_file(file):
            print(f'[cache] arquivo identico: {dest}')
            return dest
        raise FileExistsError(f'{dest} difere do arquivo importado; remova-o manualmente para substituir')
    temp = dest.with_name(dest.name + '.part')
    with file.open('rb') as source, temp.open('wb') as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    try:
        ensure_archive(temp)
        temp.replace(dest)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    print(f'[import] {file.name}: {len(names)} CSV(s) -> {dest}; sha256={hash_file(dest)}')
    return dest



def import_directory(source: Path, year: int) -> tuple[list[str], list[dict]]:
    if not source.is_dir():
        raise NotADirectoryError(source)
    good, bad = [], []
    from mapa_eleicoes.pipeline import accepted_name
    for path in sorted(source.glob('*.zip')):
        if not accepted_name(path.name, year):
            continue
        try:
            import_archive(path, year)
            good.append(path.name)
        except Exception as exc:
            bad.append({'arquivo':path.name,'erro':str(exc)})
            print(f'[ERRO IMPORT] {path.name}: {exc}')
    manifest = DATA/'raw'/str(year)/'import_manifest.json'
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps({'sucesso':good,'erro':bad},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'[IMPORT] {len(good)} aceitos, {len(bad)} rejeitados -> {manifest}')
    return good,bad


def download_tse(year: int, uf: str) -> Path:
    """Acervo oficial do TSE. Escreve .part e somente renomeia ZIP verificável."""
    from urllib.request import Request, urlopen
    uf=uf.upper()
    if not re.fullmatch(r'[A-Z]{2}',uf): raise ValueError('UF inválida')
    dest=DATA/'raw'/str(year)/f'votacao_secao_{year}_{uf}.zip'
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        ensure_archive(dest)
        print(f'[CACHE] {dest}');return dest
    url=f'https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{year}_{uf}.zip'
    tmp=dest.with_suffix('.zip.part')
    try:
        with urlopen(Request(url, headers={'User-Agent':'AtlasEleitoral/0.2'}), timeout=120) as r, tmp.open('wb') as f:
            shutil.copyfileobj(r,f,1024*1024)
        ensure_archive(tmp)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    print(f'[TSE] {dest} ({dest.stat().st_size:,} bytes), sha256={hash_file(dest)}')
    return dest

def first_key(columns: set[str], *choices: str) -> str:
    for value in choices:
        if value in columns:
            return value
    raise ValueError(f'Esperada uma destas colunas: {choices}; presentes: {sorted(columns)}')


def classify_expr(columns: set[str], number_col: str) -> pl.Expr:
    """Classificacao vetorizada. Chaves eleitorais permanecem texto."""
    kind = pl.lit('nominal')
    if 'CD_TIPO_VOTAVEL' in columns:
        code = pl.col('CD_TIPO_VOTAVEL')
        kind = (pl.when(code == '2').then(pl.lit('legenda'))
                .when(code == '3').then(pl.lit('branco'))
                .when(code == '4').then(pl.lit('nulo')).otherwise(kind))
    for column in ('DS_TIPO_VOTAVEL', 'TP_VOTO'):
        if column in columns:
            value = pl.col(column).fill_null('').str.to_lowercase()
            kind = (pl.when(value.str.contains('legenda')).then(pl.lit('legenda'))
                    .when(value.str.contains('branc')).then(pl.lit('branco'))
                    .when(value.str.contains('nul')).then(pl.lit('nulo')).otherwise(kind))
    if 'NM_VOTAVEL' in columns:
        name = pl.col('NM_VOTAVEL').fill_null('').str.to_lowercase()
        kind = (pl.when(name.str.contains('voto em branco')).then(pl.lit('branco'))
                .when(name.str.contains('voto nulo')).then(pl.lit('nulo')).otherwise(kind))
    number = pl.col(number_col).str.strip_chars()
    return (pl.when((number == '95') & (kind == 'nominal')).then(pl.lit('branco'))
            .when((number == '96') & (kind == 'nominal')).then(pl.lit('nulo'))
            .otherwise(kind).alias('tipo_voto'))


def iter_polars_batches(reader: csv.DictReader, selected: list[str], size: int):
    """Leitor CSV da stdlib e lotes Polars limitados; sem bufferizar ZIP inteiro."""
    if size < 1:
        raise ValueError('chunksize deve ser positivo')
    schema = {name.strip().upper(): pl.String for name in selected}
    batch = []
    for record in reader:
        batch.append({key.strip().upper(): record.get(key, '') for key in selected})
        if len(batch) >= size:
            yield pl.from_dicts(batch, schema=schema)
            batch = []
    if batch:
        yield pl.from_dicts(batch, schema=schema)


def process_archive(path: Path, year: int, outdir: Path | None = None, chunksize: int = 100_000) -> dict:
    """Agregacao em Polars por blocos, acumulando contagens sem carregar todo ZIP."""
    names = ensure_archive(path)
    match = re.search(r'_([A-Z]{2})\.zip$', path.name.upper())
    uf = match.group(1) if match else path.stem[-2:].upper()
    outdir = outdir or DATA / 'processed' / str(year)
    counts: Counter[tuple] = Counter()
    rows = csv_seen = 0
    cargos: set[str] = set()
    turnos: set[int] = set()
    with zipfile.ZipFile(path) as archive:
        for filename in names:
            with archive.open(filename) as binary, io.TextIOWrapper(binary, encoding='latin-1', newline='') as stream:
                reader = csv.DictReader(stream, delimiter=';')
                if not reader.fieldnames:
                    raise ValueError(f'{filename}: cabecalho CSV ausente')
                selected = [name for name in reader.fieldnames if name.strip().upper() in INPUT_COLUMNS]
                present = {name.strip().upper() for name in selected}
                if not REQUIRED.issubset(present):
                    raise ValueError(f'{filename} sem campos {REQUIRED - present}')
                number_col = first_key(present, 'NR_VOTAVEL', 'NR_CANDIDATO')
                name_col = first_key(present, 'NM_VOTAVEL', 'NM_URNA_CANDIDATO')
                cargo_col = first_key(present, 'DS_CARGO', 'DS_CARGO_PERGUNTA')
                for frame in iter_polars_batches(reader, selected, chunksize):
                    if 'ANO_ELEICAO' in present:
                        frame = frame.filter(pl.col('ANO_ELEICAO') == str(year))
                    if frame.is_empty():
                        continue
                    code = pl.col('CD_MUNICIPIO').str.strip_chars().str.strip_chars_start('0')
                    frame = frame.with_columns(
                        pl.lit(year).cast(pl.Int32).alias('ano'),
                        pl.col('NR_TURNO').cast(pl.Int16, strict=True).alias('turno'),
                        (pl.col('SG_UF').str.strip_chars().str.to_uppercase()
                            if 'SG_UF' in present else pl.lit(uf)).alias('uf'),
                        pl.when(code == '').then(pl.lit('0')).otherwise(code).alias('cd_municipio_tse'),
                        pl.col('NM_MUNICIPIO').str.strip_chars().alias('municipio'),
                        pl.col('NR_ZONA').cast(pl.Int32, strict=True).alias('zona'),
                        pl.col(cargo_col).str.strip_chars().alias('cargo'),
                        pl.col(number_col).str.strip_chars().alias('numero'),
                        pl.col(name_col).str.strip_chars().alias('candidato'),
                        classify_expr(present, number_col),
                        pl.col('QT_VOTOS').cast(pl.Int64, strict=True).alias('votos')
                    ).select(COLUMNS)
                    if (frame.get_column('votos') < 0).any():
                        raise ValueError(f'{filename}: votos negativos')
                    rows += frame.height
                    cargos.update(frame.get_column('cargo').unique().to_list())
                    turnos.update(frame.get_column('turno').unique().to_list())
                    grouped = frame.group_by(COLUMNS[:-1]).agg(pl.col('votos').sum())
                    for row in grouped.iter_rows():
                        counts[row[:-1]] += int(row[-1])
                csv_seen += 1
    if not csv_seen or not rows:
        raise ValueError(f'{path.name}: nenhuma linha util para {year}')
    outdir.mkdir(parents=True, exist_ok=True)
    schema = {name: pl.String for name in COLUMNS}
    schema.update({'ano': pl.Int32, 'turno': pl.Int16, 'zona': pl.Int32, 'votos': pl.Int64})
    df = pl.from_dicts([dict(zip(COLUMNS, (*key, votes))) for key, votes in counts.items()], schema=schema)
    df = df.sort(['turno','uf','cd_municipio_tse','zona','cargo','numero'])
    target = outdir / f'votos_{uf}.csv.gz'
    temp = outdir / f'votos_{uf}.part.csv.gz'
    try:
        with gzip.open(temp, 'wt', encoding='utf-8', newline='') as stream:
            df.write_csv(stream)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    meta = {'arquivo': path.name, 'csvs': csv_seen, 'ano': year, 'uf': uf,
            'linhas_lidas': rows, 'linhas_agregadas': df.height,
            'total_votos_linhas': int(df.get_column('votos').sum()), 'cargos': sorted(cargos),
            'turnos': sorted(turnos), 'origem': 'TSE',
            'gerado_em_utc': datetime.now(timezone.utc).isoformat()}
    (outdir / f'votos_{uf}.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    return meta

def ingest(year: int, only_uf: str = '') -> tuple[list[dict], list[dict]]:
    raw = DATA / 'raw' / str(year)
    # NUNCA misturar arquivos munzona com o formato votacao_secao.
    archives = sorted(raw.glob(f'votacao_secao_{year}_*.zip'))
    if only_uf:
        archives = [p for p in archives if p.name.upper().endswith(f'_{only_uf.upper()}.ZIP')]
    if not archives:
        raise FileNotFoundError(f'Sem ZIPs em {raw} (UF={only_uf or "todas"}). Use make import.')
    results, errors = [], []
    for path in archives:
        try:
            meta = process_archive(path, year)
            print(f'[OK] {path.name}: {meta["linhas_lidas"]:,} linhas; {meta["cargos"]}; turnos {meta["turnos"]}')
            results.append(meta)
        except Exception as exc:
            errors.append({'arquivo': path.name, 'erro': str(exc)})
            print(f'[ERRO] {path.name}: {exc}')
    summary = {'ano': year, 'concluidos': results, 'erros': errors}
    (DATA / 'processed' / str(year)).mkdir(parents=True, exist_ok=True)
    (DATA / 'processed' / str(year) / 'ingest_manifest.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    return results, errors


def geo_import(file: Path, level: str):
    import geopandas as gpd
    if not file.is_file():
        raise FileNotFoundError(file)
    if level not in ('municipio', 'zona'):
        raise ValueError('LEVEL precisa ser municipio ou zona')
    source = f'zip://{file.resolve().as_posix()}' if file.suffix.lower() == '.zip' else str(file)
    gdf = gpd.read_file(source)
    if gdf.crs is None:
        raise ValueError('Arquivo sem CRS: informe projeção no arquivo de origem')
    gdf = gdf.to_crs(4326)
    gdf['geometry'] = gdf.geometry.simplify(0.005, preserve_topology=True)
    out = DATA / 'geo' / ('municipios.geojson' if level == 'municipio' else 'zonas.geojson')
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, driver='GeoJSON')
    print(f'[GEO] {len(gdf)} polígonos -> {out} (CRS EPSG:4326)')


IBGE_UF_BY_PREFIX = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA",
    "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE",
    "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE",
    "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT",
    "52": "GO", "53": "DF",
}


def crosswalk_import(file: Path):
    """Normaliza de/para oficial TSE/IBGE mantendo codigos como strings.

    A UF pode nao existir como sigla no ZIP de origem; o prefixo do codigo
    IBGE de sete digitos determina univocamente a UF, sem cruzamento por nome.
    """
    import unicodedata

    if not file.is_file():
        raise FileNotFoundError(file)
    if file.suffix.lower() == ".zip":
        with zipfile.ZipFile(file) as archive:
            options = candidate_csv(archive)
            if not options:
                raise ValueError("ZIP sem CSV de correspondencia")
            # Nao presumir o primeiro membro quando houver documentacao.
            raw = archive.read(options[0])
    else:
        raw = file.read_bytes()
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("latin-1")
    # Evita inferencia numerica que descarta zeros a esquerda.
    first = decoded.splitlines()[0] if decoded else ""
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    df = pl.read_csv(
        io.BytesIO(decoded.encode("utf-8")), separator=delimiter,
        infer_schema=False, ignore_errors=False,
    )
    if len(df.columns) < 2:
        raise ValueError("CSV de/para deve incluir codigos TSE e IBGE")
    def normalized(name: str) -> str:
        unaccented = unicodedata.normalize("NFKD", name.strip())
        ascii_name = "".join(char for char in unaccented if not unicodedata.combining(char))
        return re.sub(r"[^A-Z0-9]+", "_", ascii_name.upper()).strip("_")

    rename = {column: normalized(column) for column in df.columns}
    if len(set(rename.values())) != len(rename):
        raise ValueError("Cabecalho de/para ambiguo apos normalizacao")
    df = df.rename(rename)
    cols = set(df.columns)
    tse = first_key(
        cols, "CD_MUNICIPIO_TSE", "COD_MUNICIPIO_TSE", "CODIGO_TSE",
        "CODIGO_MUNICIPIO_TSE", "CD_MUN_TSE", "CD_MUNICIPIO",
        "COD_TSE", "MUNICIPIO_TSE", "CD_MUN",
    )
    ibge = first_key(
        cols, "CD_MUNICIPIO_IBGE", "COD_MUNICIPIO_IBGE", "CODIGO_IBGE",
        "CODIGO_MUNICIPIO_IBGE", "CD_MUN_IBGE", "COD_IBGE",
        "CD_IBGE", "IBGE", "MUNICIPIO_IBGE", "GEOCODIGO",
    )
    uf_col = next(
        (column for column in ("SG_UF", "UF", "SIGLA_UF") if column in cols),
        None,
    )
    clean_tse = pl.col(tse).str.strip_chars().str.strip_chars_start("0")
    clean_ibge = pl.col(ibge).str.strip_chars()
    mapped = df.select(
        pl.when(clean_tse == "").then(pl.lit("0"))
        .otherwise(clean_tse).alias("cd_municipio_tse"),
        clean_ibge.alias("codigo_ibge"),
        (pl.col(uf_col).str.strip_chars().str.to_uppercase()
         if uf_col else pl.lit("")).alias("uf_original"),
    ).filter(
        pl.col("codigo_ibge").str.contains(r"^\d{7}$")
        & pl.col("cd_municipio_tse").str.contains(r"^\d+$")
    ).with_columns(
        pl.col("codigo_ibge").str.slice(0, 2)
        .replace(IBGE_UF_BY_PREFIX, default=None)
        .alias("uf_ibge")
    )
    if mapped.is_empty():
        raise ValueError("De/para sem municipio com codigo IBGE de 7 digitos")
    mapped = mapped.filter(pl.col("uf_ibge").is_not_null())
    if mapped.is_empty():
        raise ValueError("Codigo IBGE nao pertence a UF brasileira reconhecida")
    conflicts_uf = mapped.filter(
        pl.col("uf_original").is_in(list(IBGE_UF_BY_PREFIX.values()))
        & (pl.col("uf_original") != pl.col("uf_ibge"))
    )
    if not conflicts_uf.is_empty():
        raise ValueError("UF original discorda do prefixo do codigo IBGE")
    mapped = mapped.select(
        pl.col("cd_municipio_tse"),
        pl.col("codigo_ibge"),
        pl.col("uf_ibge").alias("uf"),
    ).unique()
    ambiguous = (
        mapped.group_by(["uf", "cd_municipio_tse"]).len()
        .filter(pl.col("len") > 1)
    )
    if not ambiguous.is_empty():
        raise ValueError(
            "De/para possui codigos TSE com multiplos municipios IBGE: "
            + str(ambiguous.head(5).to_dicts())
        )
    target = DATA / "reference" / "tse_ibge.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".part.csv")
    try:
        mapped.sort(["uf", "cd_municipio_tse"]).write_csv(temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[TSE/IBGE] {mapped.height:,} municipios/codigos -> {target}")

def validate(year: int):
    folder = DATA / 'processed' / str(year)
    metas = sorted(folder.glob('votos_*.json'))
    if not metas:
        raise FileNotFoundError(f'Sem manifestos em {folder}')
    failures = []
    for meta_file in metas:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        path = folder / f'votos_{meta["uf"]}.csv.gz'
        with gzip.open(path, 'rb') as source:
            df = pl.read_csv(source, schema_overrides={'votos': pl.Int64}, infer_schema=False)
        votes = df.get_column('votos').cast(pl.Int64, strict=True)
        total = int(votes.sum() or 0)
        valid = not df.is_empty() and total == meta['total_votos_linhas'] and bool((votes >= 0).all())
        print(f'[{"OK" if valid else "FAIL"}] {meta["uf"]}: {df.height:,} grupos, votos {total:,}')
        if not valid:
            failures.append(meta['uf'])
    if failures:
        raise ValueError(f'Falha nos manifestos: {failures}')

def main(argv: list[str] | None = None):
    cli = argparse.ArgumentParser(description='TSE -> Atlas Eleitoral. Invocar via Makefile.')
    sub = cli.add_subparsers(dest='command', required=True)
    for name in ('inspect','import','crosswalk','geo-import'):
        p = sub.add_parser(name); p.add_argument('--file', type=Path, required=True)
        if name == 'import': p.add_argument('--year', type=int, default=2026)
        if name == 'geo-import': p.add_argument('--level', default='municipio')
    p = sub.add_parser('import-dir');p.add_argument('--dir',type=Path,required=True);p.add_argument('--year',type=int,default=2026)
    p = sub.add_parser('download');p.add_argument('--year',type=int,default=2026);p.add_argument('--uf',required=True)
    for name in ('ingest','doctor','validate','clean-processed'):
        p = sub.add_parser(name);p.add_argument('--year', type=int, default=2026)
        if name == 'ingest': p.add_argument('--uf', default='')
    args = cli.parse_args(argv)
    if args.command == 'inspect': print(json.dumps(inspect_archive(args.file), ensure_ascii=False, indent=2))
    elif args.command == 'import': import_archive(args.file, args.year)
    elif args.command == 'crosswalk': crosswalk_import(args.file)
    elif args.command == 'download': download_tse(args.year,args.uf)
    elif args.command == 'import-dir':
        imported, errors = import_directory(args.dir,args.year)
        if errors: raise SystemExit(1)
    elif args.command == 'geo-import': geo_import(args.file, args.level)
    elif args.command == 'ingest':
        result, errors = ingest(args.year, args.uf)
        print(f'[RESUMO] Sucesso={len(result)}, erros={len(errors)}')
        if errors: raise SystemExit(1)
    elif args.command == 'validate': validate(args.year)
    elif args.command == 'doctor':
        print('Raw:', [(p.name, p.stat().st_size) for p in (DATA/'raw'/str(args.year)).glob('*.zip')])
        print('CSV agregado:', [p.name for p in (DATA/'processed'/str(args.year)).glob('*.csv.gz')])
        print('Auxiliar munzona:', [p.name for p in (DATA/'processed'/str(args.year)/'aux').glob('*') if p.is_dir()])
        print('Manifesto prepare:', (DATA/'processed'/str(args.year)/'prepare_manifest.json').exists())
        print('Geometria:', [p.name for p in (DATA/'geo').glob('*.geojson')])
        print('De/para:', (DATA/'reference'/'tse_ibge.csv').exists())
    elif args.command == 'clean-processed':
        target = DATA / 'processed' / str(args.year)
        if target.exists(): shutil.rmtree(target)
        print(f'Arquivos derivados apagados em {target}. ZIPs brutos preservados.')


if __name__ == '__main__': main()