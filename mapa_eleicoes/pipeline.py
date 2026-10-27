"""Orquestrador incremental dos dados brutos. Invocar exclusivamente com make.

Layout aceito:
  data/tse_raw_2026_bundle.zip (bundle com ZIPs originais dentro)
  data/incoming/*.zip ou data/*.zip (ZIPs TSE soltos)
  data/raw/2026/*.zip (ZIPs TSE ja organizados)

Arquivos votacao_secao sao processados para o mapa. Os tres datasets
munzona recebem um caminho separado, fiel ao esquema de origem, em Parquet.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from mapa_eleicoes import cli

DATA = cli.DATA
PIPELINE_REV = 1
AUX_PREFIXES = (
    "votacao_candidato_munzona_",
    "votacao_partido_munzona_",
    "detalhe_votacao_munzona_",
)


def accepted_name(name: str, year: int) -> bool:
    return bool(
        re.fullmatch(rf"votacao_secao_{year}_(?:BR|[A-Z]{{2}})\.zip", name)
        or any(name == f"{prefix}{year}.zip" for prefix in AUX_PREFIXES)
    )


def is_section(path: Path, year: int) -> bool:
    return bool(re.fullmatch(rf"votacao_secao_{year}_[A-Z]{{2}}\.zip", path.name))


def is_aux(path: Path, year: int) -> bool:
    return any(path.name == f"{prefix}{year}.zip" for prefix in AUX_PREFIXES)


def _safe_copy(source: Path, dest: Path, expected: str | None = None) -> bool:
    """Copia atomica; nao sobrescreve um bruto divergente."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if cli.hash_file(dest) == (expected or cli.hash_file(source)):
            return False
        raise FileExistsError(f"Conflito de dados, destino diferente: {dest}")
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    try:
        with source.open("rb") as incoming, tmp.open("wb") as output:
            shutil.copyfileobj(incoming, output, 1024 * 1024)
        cli.ensure_archive(tmp)
        actual = cli.hash_file(tmp)
        if expected is not None and actual != expected:
            raise ValueError(f"SHA-256 divergente: {source.name}")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def import_loose(year: int) -> list[str]:
    raw = DATA / "raw" / str(year)
    sources = list(DATA.glob("*.zip")) + list((DATA / "incoming").glob("*.zip"))
    imported = []
    for source in sorted(sources):
        if not accepted_name(source.name, year):
            continue
        cli.ensure_archive(source)
        dest = raw / source.name
        if _safe_copy(source, dest):
            print(f"[STAGE] {source.name} -> {dest}")
            imported.append(source.name)
        else:
            print(f"[CACHE STAGE] {source.name}")
    return imported


def bundle_path(year: int) -> Path:
    return DATA / f"tse_raw_{year}_bundle.zip"


def pack(year: int, output: Path | None = None) -> Path:
    """Bundle ZIP64 armazenado sem recomprimir os ZIPs TSE."""
    raw = DATA / "raw" / str(year)
    files = sorted(f for f in raw.glob("*.zip") if accepted_name(f.name, year))
    if not files:
        raise FileNotFoundError(f"Sem ZIPs oficiais em {raw}")
    output = output or (DATA / "bundles" / f"tse_raw_{year}_bundle.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Bundle ja existe: {output}")
    temp = output.with_name(output.name + ".part")
    manifest = {"ano": year, "criacao_utc": datetime.now(timezone.utc).isoformat(),
                "arquivos": []}
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED,
                             allowZip64=True) as archive:
            for path in files:
                cli.ensure_archive(path)
                digest = cli.hash_file(path)
                rel = f"raw/{year}/{path.name}"
                archive.write(path, arcname=rel)
                manifest["arquivos"].append({
                    "caminho": rel, "bytes": path.stat().st_size, "sha256": digest,
                })
                print(f"[BUNDLE] {path.name}")
            archive.writestr("manifest.json",
                             json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    print(f"[BUNDLE] {len(files)} arquivos -> {output}")
    return output


def unpack(bundle: Path, year: int) -> list[str]:
    """Extrai somente ZIPs TSE conhecidos, rejeitando traversal e colisoes."""
    if not bundle.is_file():
        raise FileNotFoundError(bundle)
    imported = []
    raw = DATA / "raw" / str(year)
    with zipfile.ZipFile(bundle) as archive:
        if "manifest.json" not in archive.namelist():
            raise ValueError("Bundle sem manifest.json: use make import-dir para ZIPs soltos")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("ano") != year:
            raise ValueError("Ano do bundle nao confere com ANO")
        for record in manifest.get("arquivos", []):
            rel = record["caminho"]
            parts = Path(rel).parts
            if len(parts) != 3 or parts[:2] != ("raw", str(year)):
                raise ValueError(f"Caminho inesperado no bundle: {rel}")
            filename = parts[2]
            if not accepted_name(filename, year):
                raise ValueError(f"Arquivo nao reconhecido: {filename}")
            member = archive.getinfo(rel)
            if member.is_dir() or member.file_size != record["bytes"]:
                raise ValueError(f"Tamanho incorreto: {rel}")
            dest = raw / filename
            expected = record.get("sha256")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError(f"Checksum ausente: {rel}")
            if dest.exists():
                if cli.hash_file(dest) != expected:
                    raise FileExistsError(f"Arquivo local difere do bundle: {filename}")
                print(f"[CACHE BUNDLE] {filename}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            try:
                with archive.open(member) as stream, tmp.open("wb") as output:
                    shutil.copyfileobj(stream, output, 1024 * 1024)
                if cli.hash_file(tmp) != expected:
                    raise ValueError(f"SHA-256 incorreto: {filename}")
                cli.ensure_archive(tmp)
                os.replace(tmp, dest)
                imported.append(filename)
                print(f"[UNPACK] {filename}")
            finally:
                tmp.unlink(missing_ok=True)
    return imported


def _fresh(metadata: Path, source: Path, output: Path) -> bool:
    if not metadata.exists() or not output.exists():
        return False
    try:
        entry = json.loads(metadata.read_text(encoding="utf-8"))
        stat = source.stat()
        return (entry.get("pipeline_rev") == PIPELINE_REV
                and entry.get("source_bytes") == stat.st_size
                and entry.get("source_mtime_ns") == stat.st_mtime_ns
                and entry.get("source_name") == source.name
                and entry.get("source_sha256") is not None)
    except (OSError, ValueError, TypeError):
        return False


def _stamp(metadata: Path, source: Path, entry: dict) -> dict:
    stat = source.stat()
    entry.update({
        "pipeline_rev": PIPELINE_REV,
        "source_name": source.name,
        "source_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_sha256": cli.hash_file(source),
    })
    metadata.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def _process_aux(path: Path, year: int, chunksize: int = 50000) -> dict:
    """Materializa datasets munzona SEM interpreta-los como secao eleitoral.

    Todo campo e lido como String para preservar identificadores, nulos,
    formatos e zeros. Esquema especifico e validacao eleitoral vem depois.
    """
    result_dir = DATA / "processed" / str(year) / "aux" / path.stem
    metadata = result_dir / "manifest.json"
    if _fresh(metadata, path, result_dir / "part-000001.parquet"):
        print(f"[CACHE AUX] {path.name}")
        return json.loads(metadata.read_text(encoding="utf-8"))
    result_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{path.stem}-", dir=result_dir.parent))
    rows, parts, columns = 0, 0, None
    try:
        with zipfile.ZipFile(path) as archive:
            csv_files = cli.candidate_csv(archive)
            if not csv_files:
                raise ValueError(f"Sem CSV em {path.name}")
            for filename in csv_files:
                with archive.open(filename) as binary:
                    with io.TextIOWrapper(binary, encoding="latin-1", newline="") as text:
                        reader = csv.DictReader(text, delimiter=";")
                        if not reader.fieldnames:
                            raise ValueError(f"CSV sem colunas: {filename}")
                        header = list(reader.fieldnames)
                        if columns is None:
                            columns = header
                        elif columns != header:
                            raise ValueError(f"CSV com schema diferente: {filename}")
                        for frame in cli.iter_polars_batches(reader, header, chunksize):
                            parts += 1
                            rows += frame.height
                            frame.write_parquet(staging / f"part-{parts:06d}.parquet",
                                                compression="zstd")
        if not parts:
            raise ValueError(f"Dataset sem registros: {path.name}")
        entry = {
            "arquivo": path.name, "tipo": "munzona", "ano": year,
            "linhas": rows, "partes": parts, "colunas": columns,
            "interpretacao": "Colunas originais como texto; nao agregado a votos por secao",
        }
        _stamp(staging / "manifest.json", path, entry)
        if result_dir.exists():
            backup = result_dir.with_name(result_dir.name + ".old")
            if backup.exists():
                shutil.rmtree(backup)
            result_dir.rename(backup)
            try:
                staging.rename(result_dir)
            except Exception:
                backup.rename(result_dir)
                raise
            shutil.rmtree(backup)
        else:
            staging.rename(result_dir)
        print(f"[AUX OK] {path.name}: {rows:,} linhas, {parts} arquivos Parquet")
        return entry
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def prepare(year: int, auxiliary: bool = True) -> dict:
    """Unifica staging, integridade, conversao, manifestos e validacao."""
    incoming = [bundle_path(year), DATA / "incoming" / f"tse_raw_{year}_bundle.zip"]
    errors, sections, aux_done = [], [], []
    for bundle in incoming:
        if bundle.exists():
            try:
                unpack(bundle, year)
            except Exception as exc:
                errors.append({"arquivo": bundle.name, "erro": str(exc)})
    try:
        import_loose(year)
    except Exception as exc:
        errors.append({"etapa": "import", "erro": str(exc)})
    raw = DATA / "raw" / str(year)
    output = DATA / "processed" / str(year)
    output.mkdir(parents=True, exist_ok=True)
    for path in sorted(raw.glob("*.zip")):
        if not accepted_name(path.name, year):
            print(f"[SKIP] Tipo desconhecido: {path.name}")
            continue
        try:
            cli.ensure_archive(path)
            if is_section(path, year):
                uf = path.stem.rsplit("_", 1)[-1]
                metadata = output / f"votos_{uf}.json"
                csv_path = output / f"votos_{uf}.csv.gz"
                if _fresh(metadata, path, csv_path):
                    print(f"[CACHE SECAO] {path.name}")
                else:
                    entry = cli.process_archive(path, year)
                    _stamp(metadata, path, entry)
                    print(f"[SECAO OK] {path.name}: {entry['linhas_lidas']:,} linhas")
                sections.append(path.name)
            elif is_aux(path, year):
                if auxiliary:
                    aux_done.append(_process_aux(path, year)["arquivo"])
                else:
                    print(f"[AUX ADIADO] {path.name}, AUX=0")
        except Exception as exc:
            print(f"[ERRO] {path.name}: {exc}")
            errors.append({"arquivo": path.name, "erro": str(exc)})
    if sections:
        try:
            cli.validate(year)
        except Exception as exc:
            errors.append({"etapa": "validate", "erro": str(exc)})
    else:
        errors.append({"etapa": "section", "erro": "Sem ZIP votacao_secao valido; mapa sem dados"})
    summary = {"ano": year, "secoes": sections, "munzona": aux_done,
               "erros": errors, "cobertura": "parcial ate verificacao das UFs e turnos"}
    (output / "prepare_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PREPARE] Secoes={len(sections)}, aux={len(aux_done)}, erros={len(errors)}")
    if errors:
        raise ValueError(f"Preparacao incompleta: veja {output / 'prepare_manifest.json'}")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pipeline de dados; invoke somente via Makefile")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--year", type=int, default=2026)
    prep.add_argument("--aux", choices=["0", "1"], default="1")
    pack_cmd = sub.add_parser("pack")
    pack_cmd.add_argument("--year", type=int, default=2026)
    pack_cmd.add_argument("--output", type=Path)
    unpack_cmd = sub.add_parser("unpack")
    unpack_cmd.add_argument("--year", type=int, default=2026)
    unpack_cmd.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.year, auxiliary=args.aux == "1")
    elif args.command == "pack":
        pack(args.year, args.output)
    elif args.command == "unpack":
        unpack(args.bundle, args.year)


if __name__ == "__main__":
    main()
