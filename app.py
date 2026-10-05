"""Streamlit view for the topical-mapping experiment."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from topical_map.storage import load_keywords, load_serps


st.set_page_config(page_title="Topical Map", layout="wide")
st.title("Topical Map")
st.caption("Stage 1 scaffold: keyword and SERP coverage inspection")

keywords = load_keywords()
serps = load_serps()
serp_keywords = {
    record.get("keyword")
    for record in serps
    if isinstance(record, dict) and isinstance(record.get("keyword"), str)
}
covered_count = sum(
    1 for record in keywords if isinstance(record, dict) and record.get("keyword") in serp_keywords
)

metric_columns = st.columns(3)
metric_columns[0].metric("Keywords", len(keywords))
metric_columns[1].metric("SERP records", len(serps))
coverage = f"{covered_count} / {len(keywords)}" if keywords else "0 / 0"
metric_columns[2].metric("SERP coverage", coverage)

if not keywords:
    st.info(
        "No keywords are available yet. Add records to data/keywords.json, or place "
        "tavyn_keywords.json in the project root and copy its array into that file."
    )
else:
    keyword_rows = [
        {
            "keyword": record.get("keyword", ""),
            "search_volume": record.get("search_volume"),
        }
        for record in keywords
        if isinstance(record, dict)
    ]
    keyword_df = pd.DataFrame(keyword_rows)
    search = st.text_input("Search keywords", placeholder="Filter by keyword")
    if search:
        keyword_df = keyword_df[
            keyword_df["keyword"].str.contains(search, case=False, na=False)
        ]
    st.dataframe(keyword_df, use_container_width=True, hide_index=True)

    histogram_values = keyword_df["search_volume"].dropna()
    if histogram_values.empty:
        st.info("No non-null search volumes are available for the histogram.")
    else:
        figure = px.histogram(
            keyword_df,
            x="search_volume",
            nbins=20,
            title="Search-volume distribution",
            labels={"search_volume": "Search volume"},
        )
        st.plotly_chart(figure, use_container_width=True)

if not serps:
    st.warning(
        "No SERP data is available yet. Collection is intentionally not implemented; "
        "run the placeholder with `python -m topical_map.serps update` to see its message."
    )
