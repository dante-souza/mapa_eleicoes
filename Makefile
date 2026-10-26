# Ponto unico de entrada — Windows (GNU Make/PowerShell) e Linux/macOS.
.DEFAULT_GOAL := help
ANO ?= 2026
UF ?=
FILE ?=
DIR ?=
LEVEL ?= municipio
ifeq ($(OS),Windows_NT)
PYTHON ?= py -3
VENV_PY := .venv/Scripts/python.exe
else
PYTHON ?= python3
VENV_PY := .venv/bin/python
endif
.PHONY: help bootstrap inspect import import-dir download ingest validate geo-import crosswalk run test doctor clean-processed
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
	@echo "  make run                                 painel Streamlit"
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

run: bootstrap
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