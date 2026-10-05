# research-agent-mvp

A small scaffold for a topical-mapping experiment.

Stage 1 will eventually perform deterministic analysis based on shared organic
SERP URLs. A later stage may use agents to interpret and name topical groups.
This repository contains the inspection UI, a minimal DataForSEO SERP collector,
and an exploratory shared-URL overlap explorer with deterministic anchor groups.

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

## Overlap explorer

Run `streamlit run app.py` to inspect shared URL counts and Jaccard similarity
in heatmap, relationship-graph, keyword-inspector, and distribution views.
Keywords without usable saved SERPs are excluded and reported separately. The
anchor groups are experimental, not validated SEO clusters.

In Relationship Graph, **Minimum shared URLs** (1–10, default 3) controls
membership. Anchors are chosen by descending volume (missing volumes last,
alphabetical ties). Provisional groups require direct overlap with the anchor.
One reassignment pass compares each non-anchor with all fixed anchors and chooses
the highest Jaccard among qualifying anchors, breaking ties by anchor volume and
alphabetical order. The **Strongest neighbors** and **All nonzero edges** controls
only change drawn edges, including relationships across groups.

Colors identify assigned groups; diamonds mark anchors. The group selector shows
members, their best and second-best qualifying anchors, and descriptive pairwise
statistics. A Jaccard gap of at most 5 percentage points is marked Ambiguous—an
exploratory heuristic, not a confidence probability. Singleton statistics are N/A.

**Group view** is the default: each group occupies a labeled area, with its anchor
in the center. Scroll through the areas; spacing is for readability. Singleton
groups are hidden by default and can be restored with **Hide singleton groups**.
Anchor-member links are always drawn. Enable **Show cross-group connections** to
add actual overlap edges under the existing edge filters.

**Relationship view** retains the spring graph. In either view, selecting a group
highlights its members and touching edges and opens its member table/statistics;
**All groups** clears the selection. Full-data summary counts include hidden
singletons. Display controls do not change assignments.
