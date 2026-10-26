from __future__ import annotations
import csv
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from mapa_eleicoes import cli

HEADERS = ['ANO_ELEICAO','NR_TURNO','SG_UF','CD_MUNICIPIO','NM_MUNICIPIO',
    'NR_ZONA','NR_SECAO','DS_CARGO','NR_VOTAVEL','NM_VOTAVEL','QT_VOTOS']
ROWS = [
    ['2026','1','RR','03010','BOA VISTA','1','10','Governador','13','CANDIDATO A','10'],
    ['2026','1','RR','03010','BOA VISTA','1','11','Governador','13','CANDIDATO A','20'],
    ['2026','1','RR','03010','BOA VISTA','1','11','Governador','22','CANDIDATO B','19'],
    ['2026','1','RR','03010','BOA VISTA','1','10','Governador','95','Voto em branco','2'],
    ['2026','2','RR','03010','BOA VISTA','1','10','Governador','13','CANDIDATO A','12'],
]


def sample_zip(path: Path):
    buf = io.StringIO()
    w = csv.writer(buf,delimiter=';');w.writerow(HEADERS);w.writerows(ROWS)
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('votacao_secao_2026_RR.csv',buf.getvalue().encode('latin-1'))
        z.writestr('leiame.pdf',b'%PDF-1.4')
    return path


def test_archive_inspect(tmp_path):
    p = sample_zip(tmp_path/'votacao_secao_2026_RR.zip')
    result = cli.inspect_archive(p)
    assert len(result['csvs']) == 1
    assert len(result['csvs'][0]['colunas']) == len(HEADERS)
    assert result['csvs'][0]['exemplo']['SG_UF'] == 'RR'


def test_archive_corrupt(tmp_path):
    p = tmp_path/'votacao_secao_2026_PR.zip';p.write_bytes(b'PK-not-a-zip')
    with pytest.raises(ValueError, match='invalido/incompleto'):
        cli.ensure_archive(p)


def test_zone_aggregation_separated_by_turno(tmp_path):
    p = sample_zip(tmp_path/'votacao_secao_2026_RR.zip')
    meta = cli.process_archive(p,2026,tmp_path/'result',chunksize=2)
    assert meta['linhas_lidas'] == 5
    assert meta['turnos'] == [1,2]
    out = pd.read_csv(tmp_path/'result'/'votos_RR.csv.gz',dtype={'cd_municipio_tse':str,'numero':str})
    assert out.votos.sum() == 63
    first = out[(out.turno == 1) & (out.numero == '13')]
    assert first.votos.sum() == 30
    assert out[(out.tipo_voto == 'branco')].votos.sum() == 2
    assert out.cd_municipio_tse.unique().tolist() == ['3010']
    assert json.loads((tmp_path/'result'/'votos_RR.json').read_text())['total_votos_linhas'] == 63


def test_wrong_year_errors(tmp_path):
    p = sample_zip(tmp_path/'votacao_secao_2026_RR.zip')
    with pytest.raises(ValueError,match='nenhuma linha util'):
        cli.process_archive(p,2022,tmp_path/'output')


def test_import_is_repeatable(tmp_path):
    p = sample_zip(tmp_path/'votacao_secao_2026_RR.zip')
    d = tmp_path/'raw'
    assert cli.import_archive(p,2026,d).exists()
    assert cli.import_archive(p,2026,d).exists()


def test_crosswalk(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'DATA',tmp_path)
    f=tmp_path/'codigos.csv'
    f.write_text('SG_UF;CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\nRR;03010;1400100\n')
    cli.crosswalk_import(f)
    df=pd.read_csv(tmp_path/'reference'/'tse_ibge.csv',dtype=str)
    assert df.iloc[0]['cd_municipio_tse']=='3010'
    assert df.iloc[0]['codigo_ibge']=='1400100'