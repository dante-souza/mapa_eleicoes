"""Sincronizacao seletiva com fontes oficiais TSE.

Default BR/PR: recuperar estado ausente e verificar atualização de BR
sem rebaixar os 28 ZIPs nacionais em cada inicializacao.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from mapa_eleicoes import cli

UF_CODES = (
    "AC", "AL", "AM", "AP", "BA", "BR", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)


def sync(year: int, ufs: list[str] | None = None,
         force: bool = False, root: Path | None = None,
         check_daily: bool = False) -> dict:
    """Reconcilia fontes prioritarias, guardando ultima verificacao diaria."""
    data = root or cli.DATA
    source_root = data / "raw" / str(year)
    tracking = data / "reference" / f"tse_sync_{year}.json"
    entries = {}
    if tracking.exists():
        try:
            entries = json.loads(tracking.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = {}
    now_day = datetime.now(timezone.utc).date().isoformat()
    desired = ufs or ["BR", "PR"]
    results = {"atualizados": [], "sem_alteracao": [], "cache": [], "erros": []}
    for uf in desired:
        uf = uf.upper()
        if uf not in UF_CODES:
            raise ValueError(f"UF nao reconhecida: {uf}")
        path = source_root / f"votacao_secao_{year}_{uf}.zip"
        valid = False
        if path.is_file():
            try:
                cli.ensure_archive(path)
                valid = True
            except (ValueError, zipfile.BadZipFile):
                print(f"[TSE REPARO] ZIP invalido, recuperando {uf}")
        meta_file = data / "processed" / str(year) / f"votos_{uf}.json"
        turns = []
        if meta_file.is_file():
            try:
                turns = json.loads(meta_file.read_text(encoding="utf-8")).get("turnos", [])
            except (OSError, ValueError):
                pass
        # Reconsulta diaria de BR quando a base local nao tem o segundo turno.
        stale_br = uf == "BR" and 2 not in turns
        should_refresh = (
            force or not valid
            or ((stale_br or check_daily)
                and entries.get(uf, {}).get("checked_utc_day") != now_day)
        )
        if not should_refresh:
            print(f"[TSE CACHE] {uf}: fonte ja disponivel")
            results["cache"].append(uf)
            continue
        try:
            before = cli.hash_file(path) if valid else None
            # O armazenamento padrao cli.DATA e usado no Makefile.
            if data != cli.DATA:
                raise ValueError("Raiz alternativa de sincronizacao nao suportada")
            cli.download_tse(year, uf, refresh=valid or path.exists())
            after = cli.hash_file(path)
            entries[uf] = {"checked_utc_day": now_day, "sha256": after}
            if before == after:
                results["sem_alteracao"].append(uf)
            else:
                results["atualizados"].append(uf)
        except Exception as exc:
            print(f"[TSE ERRO] {uf}: {exc}")
            results["erros"].append({"uf": uf, "erro": str(exc)})
            if not valid:
                # Sem arquivo local integro, nao pode afirmar cobertura completa.
                raise RuntimeError(
                    f"Fonte oficial {uf} nao esta disponivel/integra"
                ) from exc
            # Uma atualizacao opcional pode falhar sem corromper a ultima
            # copia local. O catalogo final registrara os turnos existentes.
    tracking.parent.mkdir(parents=True, exist_ok=True)
    tracking.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sincroniza ZIPs TSE relevantes")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--ufs", default="BR,PR")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    targets = list(UF_CODES) if args.all else [
        value.strip().upper() for value in args.ufs.split(",") if value.strip()
    ]
    summary = sync(args.year, ufs=targets, force=args.force,
                   check_daily=args.all)
    print(f"[TSE SYNC] {summary}")


if __name__ == "__main__":
    main()
