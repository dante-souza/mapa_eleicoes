"""Sync oficial seletivo sem chamadas de rede reais nos testes."""
from __future__ import annotations

import json
import zipfile

from mapa_eleicoes import cli, tse_sync


def make_zip(data, year, uf, marker="local"):
    folder = data / "raw" / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"votacao_secao_{year}_{uf}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("test.csv", f"col\n{marker}\n")
    return path


def test_missing_pr_is_downloaded_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    called = []
    def fake_download(year, uf, refresh=False):
        called.append((year, uf, refresh))
        return make_zip(tmp_path, year, uf, "new")
    monkeypatch.setattr(cli, "download_tse", fake_download)
    result = tse_sync.sync(2026, ufs=["PR"])
    assert result["atualizados"] == ["PR"]
    assert called == [(2026, "PR", False)]
    result = tse_sync.sync(2026, ufs=["PR"])
    assert result["cache"] == ["PR"]
    assert len(called) == 1


def test_old_br_revalidated_at_most_once_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    existing = make_zip(tmp_path, 2026, "BR", "first")
    meta_dir = tmp_path / "processed" / "2026"
    meta_dir.mkdir(parents=True)
    (meta_dir / "votos_BR.json").write_text(
        json.dumps({"turnos": [1]}), encoding="utf-8"
    )
    called = []
    def fake_download(year, uf, refresh=False):
        called.append((year, uf, refresh))
        return existing
    monkeypatch.setattr(cli, "download_tse", fake_download)
    result = tse_sync.sync(2026, ufs=["BR"])
    assert result["sem_alteracao"] == ["BR"]
    assert called == [(2026, "BR", True)]
    result = tse_sync.sync(2026, ufs=["BR"])
    assert result["cache"] == ["BR"]
    assert len(called) == 1


def test_br_with_both_turns_does_not_require_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    make_zip(tmp_path, 2026, "BR", "first-and-second")
    meta_dir = tmp_path / "processed" / "2026"
    meta_dir.mkdir(parents=True)
    (meta_dir / "votos_BR.json").write_text(
        json.dumps({"turnos": [1, 2]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        cli, "download_tse",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Nao deveria acessar a rede")
        )
    )
    summary = tse_sync.sync(2026, ufs=["BR"])
    assert summary["cache"] == ["BR"]


def test_missing_source_download_failure_is_not_silently_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("TSE indisponivel")
    monkeypatch.setattr(cli, "download_tse", fail)
    import pytest
    with pytest.raises(RuntimeError, match="nao esta disponivel"):
        tse_sync.sync(2026, ufs=["PR"])
