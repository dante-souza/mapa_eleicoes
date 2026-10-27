# Ponto unico de entrada — Windows (GNU Make/PowerShell) e Linux/macOS.
.DEFAULT_GOAL := help
ANO ?= 2026
UF ?=
FILE ?=
DIR ?=
LEVEL ?= municipio
AUX ?= 1
GEO_YEAR ?= 2025
MALHA ?=
CROSSWALK ?=
SIMPLIFY_METERS ?= 1000
FORCE ?= 0
BUNDLE ?= data/bundles/tse_raw_$(ANO)_bundle.zip
ifeq ($(OS),Windows_NT)
PYTHON ?= py -3
VENV_PY := .venv/Scripts/python.exe
else
PYTHON ?= python3
VENV_PY := .venv/bin/python
endif
.PHONY: help bootstrap inspect import import-dir download ingest validate geo-import crosswalk run test doctor clean-processed prepare-data data-pack data-unpack data-scan geo-setup geo-check preview offices
help:
	@echo "Atlas Eleitoral / Make como ponto de entrada"
	@echo "  make bootstrap                           instala uv + requirements"
	@echo "  make inspect FILE=arquivo.zip           inspeciona ZIP sem extrair"
	@echo "  make import FILE=arquivo.zip            copia ZIP para data/raw/ANO"
	@echo "  make import-dir DIR=../Downloads            importa ZIPs de uma pasta"
	@echo "  make download UF=BR                       baixa ZIP presidencial do TSE"
	@echo "  make ingest ANO=2026 [UF=RR]            agrega votacao por municipio/zona"
	@echo "  make crosswalk FILE=de_para.csv         importa correspondencia TSE/IBGE"
	@echo "  make geo-import                         prepara malha municipal oficial (auto/cache)"
	@echo "  make geo-import FILE=malha.gpkg          prepara GeoJSON municipal"
	@echo "  make geo-import FILE=zonas.geojson LEVEL=zona"
	@echo "  make geo-setup GEO_YEAR=2025            download oficial IBGE/TSE + normalizacao"
	@echo "  make geo-setup MALHA=... CROSSWALK=...  importar malha e de/para locais"
	@echo "  make geo-check ANO=2026                 conferir cobertura geocodigo TSE/IBGE"
	@echo "  make offices ANO=2026                   listar cargos/turnos e checar BR"
	@echo "  make preview                            abrir mapa com dados ja processados (parciais)"
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

# Sem FILE, usa o mesmo setup oficial (com cache) de make geo-setup.
# LEVEL=zona sem FILE falha de maneira explicita, sem inventar limites.
geo-import: bootstrap
	$(VENV_PY) -m mapa_eleicoes.geography import $(if $(strip $(FILE)),--file "$(FILE)",) --level $(LEVEL) --geo-year $(GEO_YEAR) --simplify-meters $(SIMPLIFY_METERS) $(if $(filter 1,$(FORCE)),--force,)

# Operacao pontual, com cache: nao redescarrega 226 MB no make run.
# MALHA/CROSSWALK podem apontar ZIPs/GeoJSON/CSV baixados manualmente.
geo-setup: bootstrap
	$(VENV_PY) -m mapa_eleicoes.geography setup --geo-year $(GEO_YEAR) --simplify-meters $(SIMPLIFY_METERS) $(if $(MALHA),--malha "$(MALHA)",) $(if $(CROSSWALK),--crosswalk "$(CROSSWALK)",) $(if $(filter 1,$(FORCE)),--force,)

geo-check: bootstrap
	$(VENV_PY) -m mapa_eleicoes.geography check --year $(ANO)

# Relatorio fiel aos CSV.gz locais: lista cargos/turnos/UF e situacao BR.
offices: bootstrap
	$(VENV_PY) -m mapa_eleicoes.office_catalog --year $(ANO)

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

# Preview explicito para explorar processamento parcial (ex.: PR corrompido).
# Nao altera/manipula dados nem afirma cobertura completa.
preview: bootstrap
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