"""CLI interna. Execute as tarefas SOMENTE pelos targets do Makefile."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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
    for path in sorted(source.glob(f'votacao_secao_{year}_*.zip')):
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


def classify(chunk: pd.DataFrame, number: str) -> pd.Series:
    # TSE 2026 nao traz necessariamente CD_TIPO_VOTAVEL, mas traz NM_VOTAVEL.
    typ = pd.Series('nominal', index=chunk.index, dtype='object')
    if 'CD_TIPO_VOTAVEL' in chunk:
        typ = chunk['CD_TIPO_VOTAVEL'].map({'1':'nominal','2':'legenda','3':'branco','4':'nulo'}).fillna(typ)
    for col in ('DS_TIPO_VOTAVEL', 'TP_VOTO'):
        if col in chunk:
            series = chunk[col].str.lower()
            for match, cls in [('legenda','legenda'),('branc','branco'),('nul','nulo')]:
                typ.loc[series.str.contains(match, na=False)] = cls
    # Codigos 95/96 normalmente sao reservados; nao dependemos deles se nomes estiverem disponiveis.
    names = chunk.get('NM_VOTAVEL', pd.Series('', index=chunk.index)).str.lower()
    typ.loc[names.str.contains('voto em branco', na=False)] = 'branco'
    typ.loc[names.str.contains('voto nulo', na=False)] = 'nulo'
    typ.loc[(chunk[number].str.strip() == '95') & (typ == 'nominal')] = 'branco'
    typ.loc[(chunk[number].str.strip() == '96') & (typ == 'nominal')] = 'nulo'
    return typ


def process_archive(path: Path, year: int, outdir: Path | None = None, chunksize: int = 100_000) -> dict:
    """Incremental: mantem contadores por municipio/zona, nunca todos os votos em RAM."""
    names = ensure_archive(path)
    archive_uf = re.search(r'_([A-Z]{2})\.zip$', path.name.upper())
    uf = archive_uf.group(1) if archive_uf else path.stem[-2:].upper()
    outdir = outdir or DATA / 'processed' / str(year)
    counts: Counter[tuple] = Counter()
    rows = 0
    csv_seen = 0
    cargos: set[str] = set()
    turnos: set[int] = set()
    with zipfile.ZipFile(path) as z:
        for filename in names:
            with z.open(filename) as stream:
                try:
                    reader = pd.read_csv(stream, sep=';', encoding='latin-1', dtype=str,
                        keep_default_na=False, chunksize=chunksize,
                        usecols=lambda c: c.upper() in INPUT_COLUMNS)
                    for chunk in reader:
                        chunk.columns = chunk.columns.str.upper()
                        present = set(chunk.columns)
                        if not REQUIRED.issubset(present):
                            raise ValueError(f'{filename} sem campos {REQUIRED - present}')
                        vote_number = first_key(present, 'NR_VOTAVEL', 'NR_CANDIDATO')
                        vote_name = first_key(present, 'NM_VOTAVEL', 'NM_URNA_CANDIDATO')
                        cargo = first_key(present, 'DS_CARGO', 'DS_CARGO_PERGUNTA')
                        chunk['ano'] = year
                        if 'ANO_ELEICAO' in chunk:
                            chunk = chunk[chunk['ANO_ELEICAO'] == str(year)].copy()
                        if chunk.empty:
                            continue
                        chunk['turno'] = pd.to_numeric(chunk['NR_TURNO'], errors='raise').astype('int16')
                        chunk['uf'] = chunk['SG_UF'].str.strip().str.upper() if 'SG_UF' in chunk else uf
                        chunk['cd_municipio_tse'] = chunk['CD_MUNICIPIO'].str.strip().str.lstrip('0').replace('', '0')
                        chunk['municipio'] = chunk['NM_MUNICIPIO'].str.strip()
                        chunk['zona'] = pd.to_numeric(chunk['NR_ZONA'], errors='raise').astype('int32')
                        chunk['cargo'] = chunk[cargo].str.strip()
                        chunk['numero'] = chunk[vote_number].str.strip()
                        chunk['candidato'] = chunk[vote_name].str.strip()
                        chunk['tipo_voto'] = classify(chunk, vote_number)
                        chunk['votos'] = pd.to_numeric(chunk['QT_VOTOS'], errors='raise').astype('int64')
                        if (chunk['votos'] < 0).any():
                            raise ValueError(f'{filename}: votos negativos')
                        rows += len(chunk)
                        cargos.update(chunk['cargo'].unique().tolist())
                        turnos.update(chunk['turno'].unique().tolist())
                        grouped = chunk.groupby(COLUMNS[:-1], as_index=False, dropna=False, sort=False)['votos'].sum()
                        for row in grouped.itertuples(index=False, name=None):
                            counts[row[:-1]] += int(row[-1])
                    csv_seen += 1
                except (pd.errors.ParserError, UnicodeDecodeError) as exc:
                    raise ValueError(f'Erro no CSV {filename} em {path.name}: {exc}') from exc
    if not csv_seen or not rows:
        raise ValueError(f'{path.name}: nenhuma linha util para {year}')
    outdir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([(*k, v) for k,v in counts.items()], columns=COLUMNS)
    df = df.sort_values(['turno','uf','cd_municipio_tse','zona','cargo','numero'])
    destination = outdir / f'votos_{uf}.csv.gz'
    temp = outdir / f'votos_{uf}.part.csv.gz'
    df.to_csv(temp, index=False, compression='gzip')
    temp.replace(destination)
    meta = {'arquivo': path.name, 'csvs': csv_seen, 'ano': year, 'uf': uf,
            'linhas_lidas': rows, 'linhas_agregadas': len(df),
            'total_votos_linhas': int(df['votos'].sum()), 'cargos': sorted(cargos),
            'turnos': sorted(turnos), 'origem': 'TSE',
            'gerado_em_utc': datetime.now(timezone.utc).isoformat()}
    (outdir / f'votos_{uf}.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    return meta


def ingest(year: int, only_uf: str = '') -> tuple[list[dict], list[dict]]:
    raw = DATA / 'raw' / str(year)
    archives = sorted(raw.glob('*.zip'))
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


def crosswalk_import(file: Path):
    """Aceita CSV com codigo TSE e codigo IBGE. Nunca faz join pelo nome da cidade."""
    if not file.exists():
        raise FileNotFoundError(file)
    if file.suffix.lower() == '.zip':
        with zipfile.ZipFile(file) as z:
            src = candidate_csv(z)[0]
            with z.open(src) as f:
                data = f.read()
        df = pd.read_csv(io.BytesIO(data), sep=';', encoding='latin-1', dtype=str, keep_default_na=False)
    else:
        try:
            df = pd.read_csv(file, sep=';', encoding='utf-8-sig', dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            df = pd.read_csv(file, sep=';', encoding='latin-1', dtype=str, keep_default_na=False)
    if len(df.columns) == 1:
        raise ValueError('CSV deve usar separador ; e conter codigos TSE/IBGE')
    df.columns = [c.strip().upper() for c in df.columns]
    cols = set(df.columns)
    tse = first_key(cols,'CD_MUNICIPIO_TSE','COD_MUNICIPIO_TSE','CODIGO_TSE','CODIGO_MUNICIPIO_TSE','CD_MUN_TSE','CD_MUNICIPIO','COD_TSE')
    ibge = first_key(cols,'CD_MUNICIPIO_IBGE','COD_MUNICIPIO_IBGE','CODIGO_IBGE','CODIGO_MUNICIPIO_IBGE','CD_MUN_IBGE','COD_IBGE','CD_IBGE')
    uf = next((c for c in ('SG_UF','UF','SIGLA_UF') if c in cols), None)
    mapped = pd.DataFrame({'cd_municipio_tse': df[tse].str.strip().str.lstrip('0').replace('', '0'),
                           'codigo_ibge': df[ibge].str.strip(),
                           'uf': df[uf].str.upper().str.strip() if uf else ''})
    mapped = mapped[mapped['codigo_ibge'].str.fullmatch(r'\d{7}')].drop_duplicates()
    if mapped.empty:
        raise ValueError('Sem linhas validas com codigo IBGE de 7 digitos')
    out = DATA / 'reference' / 'tse_ibge.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    mapped.to_csv(out, index=False)
    print(f'[TSE/IBGE] {len(mapped)} codigos -> {out}')


def validate(year: int):
    folder = DATA / 'processed' / str(year)
    metas = sorted(folder.glob('votos_*.json'))
    if not metas:
        raise FileNotFoundError(f'Sem manifestos em {folder}')
    failures = []
    for meta_file in metas:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        p = folder / f'votos_{meta["uf"]}.csv.gz'
        df = pd.read_csv(p)
        valid = not df.empty and int(df.votos.sum()) == meta['total_votos_linhas'] and (df.votos >= 0).all()
        print(f'[{"OK" if valid else "FAIL"}] {meta["uf"]}: {len(df):,} grupos, votos {df.votos.sum():,}')
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
        print('Geometria:', [p.name for p in (DATA/'geo').glob('*.geojson')])
        print('De/para:', (DATA/'reference'/'tse_ibge.csv').exists())
    elif args.command == 'clean-processed':
        target = DATA / 'processed' / str(args.year)
        if target.exists(): shutil.rmtree(target)
        print(f'Arquivos derivados apagados em {target}. ZIPs brutos preservados.')


if __name__ == '__main__': main()