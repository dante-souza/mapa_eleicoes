# Ponto unico de entrada — Windows (GNU Make/PowerShell) e Linux/macOS.
.DEFAULT_GOAL := help
ANO ?= 2026
UF ?=
FILE ?=
DIR ?=
LEVEL ?= municipio
AUX ?= 1
BUNDLE ?= data/bundles/tse_raw_$(ANO)_bundle.zip
ifeq ($(OS),Windows_NT)
PYTHON ?= py -3
VENV_PY := .venv/Scripts/python.exe
else
PYTHON ?= python3
VENV_PY := .venv/bin/python
endif
.PHONY: help bootstrap inspect import import-dir download ingest validate geo-import crosswalk run test doctor clean-processed prepare-data data-pack data-unpack data-scan
help:
	@echo "Atlas Eleitoral / Make como ponto de entrada"
	@echo "  make bootstrap                           instala uv + requirements"
	@echo "  make inspect FILE=arquivo.zip           inspeciona ZIP sem extrair"
	@echo "  make import FILE=arquivo.zip            copia ZIP para data/raw/ANO"
	@echo "  make import-dir DIR=../Downloads            importa ZIPs de uma pasta"
	@echo "  make download UF=BR                       baixa ZIP presidencial do TSE"
	@echo "  make ingest ANO=2026 [UF=RR]            agrega votacao por municipio/zona"
	@echo "  make crosswalk FILE=de_para.csv         importa correspondencia TSE/IBGE"
	@echo "  make geo-import FILE=malha.gpkg          prepara GeoJSON municipal"
	@echo "  make geo-import FILE=zonas.geojson LEVEL=zona"
	@echo "  make prepare-data ANO=2026 DIR=C:/Downloads   le ZIPs de DIR e processa"
	@echo "  make data-pack ANO=2026                 gera data/bundles/tse_raw_2026_bundle.zip"
	@echo "  make data-unpack BUNDLE=arquivo.zip     extrai bundle para data/raw/ANO/"
	@echo "  make data-scan DIR=C:/Downloads ANO=2026   lista ZIPs encontrados antes de processar"
	@echo "  make run ANO=2026 DIR=C:/Downloads     importa, valida e abre Streamlit"
	@echo "  make validate / test / doctor / clean-processed"

$(VENV_PY):
	$(PYTHON) -m venv .venv

$(VENV_PY).ready: $(VENV_PY) requirements.txt
	$(VENV_PY) -m pip install uv
	$(VENV_PY) -m uv pip install --python $(VENV_PY) -r requirements.txt
	$(VENV_PY) -c "from pathlib import Path; Path('$(VENV_PY).ready').touch()"

bootstrap: $(VENV_PY).ready

inspect: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli inspect --file "$(FILE)"

import: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli import --file "$(FILE)" --year $(ANO)

import-dir: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli import-dir --dir "$(DIR)" --year $(ANO)

download: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli download --year $(ANO) --uf "$(UF)"

ingest: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli ingest --year $(ANO) $(if $(UF),--uf $(UF),)

crosswalk: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli crosswalk --file "$(FILE)"

geo-import: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli geo-import --file "$(FILE)" --level $(LEVEL)

validate: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli validate --year $(ANO)

doctor: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli doctor --year $(ANO)

# Preparacao incremental, idempotente: ZIPs por secao -> CSV.gz;
# agregados munzona -> Parquet tipado como texto (sem perder codigos).
# Arquivos ausentes nao sao baixados automaticamente.
# DIR e opcional: sem DIR, procurar em data/ e data/incoming.
# Com DIR, procurar tambem na pasta externa e importar todos os ZIPs reconhecidos.
data-scan: bootstrap
	$(VENV_PY) -m mapa_eleicoes.pipeline scan --year $(ANO) $(if $(DIR),--source-dir "$(DIR)",)

prepare-data: bootstrap
	$(VENV_PY) -m mapa_eleicoes.pipeline prepare --year $(ANO) --aux $(AUX) $(if $(DIR),--source-dir "$(DIR)",)

data-pack: bootstrap
	$(VENV_PY) -m mapa_eleicoes.pipeline pack --year $(ANO)

data-unpack: bootstrap
	$(VENV_PY) -m mapa_eleicoes.pipeline unpack --year $(ANO) --bundle "$(BUNDLE)"

run: prepare-data
	$(VENV_PY) -m streamlit run app.py

test: bootstrap
	$(VENV_PY) -m pytest -q

clean-processed: bootstrap
	$(VENV_PY) -m mapa_eleicoes.cli clean-processed --year $(ANO)

# Diagnostico do ambiente isolado sem PyPI. Nao substitui make test.
.PHONY: test-offline
test-offline:
	$(PYTHON) -m pytest -q

# Alvos de teste offline para ambientes sem PyPI; nunca usados no fluxo operacional normal.
.PHONY: inspect-offline ingest-offline validate-offline compile-offline
inspect-offline:
	$(PYTHON) -m mapa_eleicoes.cli inspect --file "$(FILE)"
ingest-offline:
	$(PYTHON) -m mapa_eleicoes.cli ingest --year $(ANO) $(if $(UF),--uf $(UF),)
validate-offline:
	$(PYTHON) -m mapa_eleicoes.cli validate --year $(ANO)
compile-offline:
	$(PYTHON) -m compileall -q mapa_eleicoes app.py tests
.PHONY: import-offline
import-offline:
	$(PYTHON) -m mapa_eleicoes.cli import --file "$(FILE)" --year $(ANO)