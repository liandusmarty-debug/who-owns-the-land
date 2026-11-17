.PHONY: setup build sample test lint serve clean

setup:        ## install Python deps into .venv (needs uv: https://docs.astral.sh/uv/)
	uv sync

build:        ## rebuild every output from data/raw (real data)
	uv run wotl build

sample:       ## rebuild using a synthetic city (no downloads) -> outputs/_sample/
	uv run wotl build --sample

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

serve:        ## preview the site at http://localhost:8000/map.html
	cd outputs && python3 -m http.server 8000

clean:        ## remove derived data (raw data is never touched)
	rm -rf data/processed/* outputs/*
	touch data/processed/.gitkeep outputs/.gitkeep
