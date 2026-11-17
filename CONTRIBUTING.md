# Contributing

Thanks for helping make land ownership in South Africa easier to understand.

## Ground rules

1. **Area-level only.** Read [PRIVACY.md](PRIVACY.md). Personal data about people or households is never accepted.
2. **Public or properly licensed data only.** Every dataset goes in `config/pipeline.toml` with its publisher, licence and URL.
3. **Reproducible.** Never edit raw data by hand. Every change happens in code under `src/wotl/`.
4. **Neutral.** Outputs describe the data. They don't argue a position.
5. **Light.** The site must stay usable on a low-end phone on a slow connection, so no frameworks or
   web fonts in `web/`. CI checks the size of the published site.

## Getting set up

```bash
make setup     # needs uv: https://docs.astral.sh/uv/
make sample    # full pipeline on synthetic data -> outputs/_sample/map.html
make test
make lint
```

Optional: install the git hooks with `uv run pre-commit install`. They run the formatter and stop you
committing data files.

## Workflow

- Branch from `main`, open a pull request, and fill in the checklist. CI must pass before merging.
- Keep pull requests small and focused. Squash-merge is the default.
- Core logic belongs in `src/wotl/`. Notebooks in `notebooks/` are for exploration only.

## Where help is most useful

- Confirming source URLs and licences (`[[sources]]` in `config/pipeline.toml`)
- Mapping real Stats SA column names (`[census.column_map]`)
- Plain-language explanations and translations (isiXhosa, Afrikaans)
- Testing the map on older phones
