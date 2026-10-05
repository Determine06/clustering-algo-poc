# research-agent-mvp

A small scaffold for a topical-mapping experiment.

Stage 1 will eventually perform deterministic analysis based on shared organic
SERP URLs. A later stage may use agents to interpret and name topical groups.
This repository currently contains the inspection UI, a minimal DataForSEO SERP
collector, and a placeholder for overlap analysis. No clustering algorithm has
been chosen.

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
* `database/serp_data.json` is an array of keyword records with `fetched_at` and
  ranked `{ "rank", "url", "title" }` results. A missing file is treated as an
  empty array.

Storage paths are resolved from the project root, so the app works regardless
of the directory from which Streamlit is launched.

## Collect SERPs

1. Install dependencies with `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` if `.env` does not already exist.
3. Fill in the API login and API password from DataForSEO API Access.
4. Test the first five missing keywords with
   `python -m topical_map.serps update --limit 5`.
5. Fetch all remaining missing keywords with
   `python -m topical_map.serps update --workers 10`.

The collector uses 10 concurrent workers by default, saves each successful
response immediately on the main thread, and skips keywords already present in
`database/serp_data.json`. Use `--workers 1` for sequential processing. Failed
keywords remain eligible for the next run.

## Placeholder

`topical_map/overlap.py` documents the future URL-set comparison, pairwise
overlap calculation, and weighted NetworkX keyword graph. It does not select
or implement a clustering algorithm yet.
