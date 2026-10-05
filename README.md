# research-agent-mvp

A small scaffold for a topical-mapping experiment.

Stage 1 will eventually perform deterministic analysis based on shared organic
SERP URLs. A later stage may use agents to interpret and name topical groups.
This repository currently contains only the inspection UI and placeholders for
SERP collection and overlap analysis. No clustering algorithm has been chosen.

## Environment setup

Python 3.11 or newer is required. From the project directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start the local browser UI with:

```bash
streamlit run app.py
```

The app shows keyword counts, SERP coverage, a searchable keyword/volume
table, and a Plotly search-volume histogram. Null search volumes are retained
in the table and omitted from the histogram.

## Data files

Data is stored in JSON files under `database/`:

* `database/keyword_list.json` is an array of `{ "keyword", "search_volume" }`
  records. `search_volume` may be `null`.
* `database/serps.json` is an array of keyword records with `fetched_at` and
  ranked `{ "rank", "url", "title" }` results. A missing file is treated as an
  empty array until SERP collection is implemented.

Storage paths are resolved from the project root, so the app works regardless
of the directory from which Streamlit is launched.

## Placeholders

`python -m topical_map.serps update` currently explains that collection is not
implemented and exits without calling an API or changing files. The intended
behavior is to fetch only missing keywords, save successful results, and leave
failures eligible for the next run.

`topical_map/overlap.py` documents the future URL-set comparison, pairwise
overlap calculation, and weighted NetworkX keyword graph. It does not select
or implement a clustering algorithm yet.
