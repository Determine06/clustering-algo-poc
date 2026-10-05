"""Streamlit view for the topical-mapping experiment."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from topical_map.clustering import AnchorGroups, build_anchor_groups
from topical_map.overlap import (
    OverlapAnalysis,
    build_overlap_analysis,
    get_pair,
    graph_edges,
    positive_neighbors,
    result_count_distribution,
)
from topical_map.storage import load_keywords, load_serps
from topical_map.visuals import (
    graph_figure, heatmap_figure, spring_layout, group_layout, group_figure, group_view_edges,
)


@st.cache_data(show_spinner="Calculating SERP overlap...")
def cached_overlap_analysis(
    keyword_records: list[dict],
    serp_records: list[dict],
) -> OverlapAnalysis:
    return build_overlap_analysis(keyword_records, serp_records)


@st.cache_data(show_spinner="Assigning anchor groups...")
def cached_anchor_groups(
    keyword_records: list[dict], serp_records: list[dict], minimum_shared: int,
) -> AnchorGroups:
    # Only file content and the membership threshold participate in this cache.
    return build_anchor_groups(
        cached_overlap_analysis(keyword_records, serp_records), minimum_shared,
    )


@st.cache_data(show_spinner="Laying out relationship graph...")
def cached_graph_layout(
    nodes: tuple[str, ...],
    weighted_edges: tuple[tuple[str, str, float], ...],
) -> dict[str, tuple[float, float]]:
    return spring_layout(nodes, weighted_edges)


def ranking_rows(analysis: OverlapAnalysis, keyword: str) -> list[dict]:
    return [
        {"rank": result.rank, "title": result.title, "url": result.url}
        for result in analysis.evidence[keyword].results
    ]



def show_group_details(analysis, groups, selected_anchor):
    stats = groups.statistics[selected_anchor]
    stat_columns = st.columns(2)
    stat_columns[0].metric(
        "Average member-pair Jaccard",
        "N/A" if stats.average_jaccard is None else f"{stats.average_jaccard:.2%}",
    )
    stat_columns[1].metric(
        "Member pairs with zero overlap",
        "N/A" if stats.zero_overlap_fraction is None else f"{stats.zero_overlap_fraction:.2%}",
    )
    st.caption(
        "Descriptive statistics include all unique member pairs, including the anchor, "
        "and exclude self-comparisons. They do not split groups."
    )
    member_rows = []
    for keyword in groups.members[selected_anchor]:
        assignment = groups.assignments[keyword]
        member_rows.append({
            "Keyword": keyword,
            "Search volume": analysis.evidence[keyword].search_volume,
            "Shared URLs with anchor": assignment.best.shared_count,
            "Jaccard with anchor": f"{assignment.best.jaccard:.2%}",
            "Second-best qualifying anchor": assignment.second.anchor if assignment.second else None,
            "Second-best Jaccard": f"{assignment.second.jaccard:.2%}" if assignment.second else None,
            "Ambiguous": assignment.ambiguous,
        })
    st.dataframe(pd.DataFrame(member_rows), use_container_width=True, hide_index=True)
    st.caption(
        "Ambiguous means the two best qualifying anchors differ by at most 5 percentage "
        "points in Jaccard. This is an exploratory heuristic, not a confidence probability. "
        "Anchors stay fixed; their table rows show self-overlap (100% Jaccard)."
    )


st.set_page_config(page_title="Topical Map", layout="wide")
st.title("Topical Map")
st.caption("Deterministic exploration of keyword and organic SERP evidence")

keywords = load_keywords()
serps = load_serps()
serp_keywords = {
    record.get("keyword")
    for record in serps
    if isinstance(record, dict) and isinstance(record.get("keyword"), str)
}
covered_count = sum(
    1
    for record in keywords
    if isinstance(record, dict) and record.get("keyword") in serp_keywords
)

metric_columns = st.columns(3)
metric_columns[0].metric("Keywords", len(keywords))
metric_columns[1].metric("SERP records", len(serps))
coverage = f"{covered_count} / {len(keywords)}" if keywords else "0 / 0"
metric_columns[2].metric("SERP coverage", coverage)

if not keywords:
    st.info("No keywords are available. Add records to database/keyword_list.json.")
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
            keyword_df["keyword"].str.contains(
                search,
                case=False,
                na=False,
                regex=False,
            )
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
        "No SERP data is available. Run `python -m topical_map.serps update` "
        "after configuring DataForSEO credentials."
    )

st.divider()
st.header("Overlap Explorer")
st.caption(
    "Exploratory views based only on shared saved organic ranking URLs. "
    "Visual groupings are not validated clusters."
)

analysis = cached_overlap_analysis(keywords, serps)
eligible_keywords = list(analysis.keywords)
pair_count = len(analysis.pairs)
explorer_metrics = st.columns(3)
explorer_metrics[0].metric("Eligible keywords", len(eligible_keywords))
explorer_metrics[1].metric("Excluded without usable SERPs", len(analysis.excluded_keywords))
explorer_metrics[2].metric("Compared keyword pairs", pair_count)

if analysis.excluded_keywords:
    with st.expander("Keywords excluded because usable SERP evidence is missing"):
        st.dataframe(
            pd.DataFrame({"keyword": analysis.excluded_keywords}),
            use_container_width=True,
            hide_index=True,
        )

if not eligible_keywords:
    st.info("No keywords have usable saved SERP URLs yet.")
    st.stop()

heatmap_tab, graph_tab, inspector_tab, distribution_tab = st.tabs(
    ("Heatmap", "Relationship Graph", "Keyword Inspector", "Distribution")
)

with heatmap_tab:
    heatmap_controls = st.columns((2, 1))
    selected_subset = heatmap_controls[0].multiselect(
        "Keyword subset",
        eligible_keywords,
        default=[],
        placeholder="All eligible keywords",
        help="Leave empty to show all eligible keywords in alphabetical order.",
    )
    heatmap_metric = heatmap_controls[1].radio(
        "Color metric",
        ("Shared URL count", "Jaccard similarity"),
        horizontal=True,
    )
    heatmap_keywords = selected_subset or eligible_keywords
    if len(heatmap_keywords) < 2:
        st.info("Select at least two keywords for pairwise comparison.")
    else:
        st.plotly_chart(
            heatmap_figure(
                analysis,
                heatmap_keywords,
                "shared" if heatmap_metric == "Shared URL count" else "jaccard",
            ),
            use_container_width=True,
        )
        if len(heatmap_keywords) > 50:
            st.caption("Axis labels are hidden in the full view; use hover and zoom to inspect cells.")

with graph_tab:
    minimum_shared = st.slider("Minimum shared URLs", 1, 10, 3)
    st.caption(
        "Experimental setting, not a validated SEO threshold. Membership requires "
        "direct overlap with an anchor; Jaccard selects the best qualifying anchor "
        "in one reassignment pass."
    )
    groups = cached_anchor_groups(keywords, serps, minimum_shared)
    multi_groups = [group for group in groups.members.values() if len(group) > 1]
    group_metrics = st.columns(4)
    group_metrics[0].metric("Groups with 2+ keywords", len(multi_groups))
    group_metrics[1].metric("Keywords in those groups", sum(map(len, multi_groups)))
    group_metrics[2].metric("Singleton keywords", sum(len(group) == 1 for group in groups.members.values()))
    group_metrics[3].metric("Ambiguous keywords", sum(item.ambiguous for item in groups.assignments.values()))
    st.divider()
    st.caption("Graph display controls — these do not change group membership or the full-data counts above.")
    view = st.radio("Graph view", ("Group view", "Relationship view"), horizontal=True)
    is_group_view = view == "Group view"
    if is_group_view:
        display_columns = st.columns(2)
        hide_singletons = display_columns[0].checkbox("Hide singleton groups", value=True, key="hide_singletons")
        show_cross_group = display_columns[1].checkbox("Show cross-group connections", value=False, key="show_cross_group")
    selected_anchor = st.selectbox(
        "Group anchor", (None, *groups.anchors),
        format_func=lambda anchor: "All groups" if anchor is None else f"{anchor} ({len(groups.members[anchor])} keywords)",
        key="selected_group",
    )
    graph_controls = st.columns((1, 1, 2))
    show_all_edges = graph_controls[0].checkbox("All nonzero edges")
    neighbor_count = graph_controls[1].slider(
        "Strongest neighbors",
        min_value=1,
        max_value=10,
        value=5,
        disabled=show_all_edges,
    )
    highlighted = graph_controls[2].selectbox(
        "Highlight keyword",
        ("None", *eligible_keywords),
    )
    displayed_edges = graph_edges(
        analysis,
        neighbors_per_keyword=neighbor_count,
        all_nonzero=show_all_edges,
    )
    if is_group_view:
        positions, centers, columns = group_layout(groups, hide_singletons)
        displayed_edges = group_view_edges(analysis, groups, positions, displayed_edges, show_cross_group)
        visible_groups = len(centers)
    else:
        weighted_edges = tuple(
            (edge.keyword_a, edge.keyword_b, edge.jaccard) for edge in displayed_edges
        )
        positions = cached_graph_layout(tuple(eligible_keywords), weighted_edges)
        visible_groups = len(groups.anchors)
    st.caption(
        f"Visible: {len(positions):,} keywords in {visible_groups:,} groups; {len(displayed_edges):,} edges. "
        "The edge control filters only what is drawn, including cross-group relationships. "
        "It does not change group membership or the underlying overlap calculations."
    )
    selected_keyword = None if highlighted == "None" else highlighted
    if is_group_view:
        if not positions:
            st.info("No groups are visible. Turn off Hide singleton groups to show singleton keywords.")
        else:
            with st.container(height=820):
                st.plotly_chart(
                    group_figure(analysis, groups, positions, centers, columns, displayed_edges, selected_keyword, selected_anchor),
                    use_container_width=True,
                )
        if selected_anchor is not None and selected_anchor not in centers:
            st.info("The selected group is a hidden singleton. Turn off Hide singleton groups to see it; its details remain below.")
        st.caption("Group areas and radial spacing are for readability, not similarity measurements. Scroll to see all areas; zoom for detail.")
    else:
        st.plotly_chart(
            graph_figure(analysis, displayed_edges, positions, selected_keyword, groups, selected_anchor),
            use_container_width=True,
        )
    st.caption(
        "Colors indicate assigned anchor groups; diamonds are anchors and circles are members. "
        "The highlighted keyword has a dark outline. Graph distance is a seeded layout aid, "
        "not an exact similarity score. Disconnected islands are layout components, not groups."
    )
    if selected_anchor is None:
        st.info("Select a group anchor to see its members and pairwise statistics.")
    else:
        show_group_details(analysis, groups, selected_anchor)
with inspector_tab:
    inspected_keyword = st.selectbox(
        "Keyword to inspect (type to search)",
        eligible_keywords,
    )
    neighbors = positive_neighbors(analysis, inspected_keyword)[:20]
    if not neighbors:
        st.info("This keyword has no positive-overlap neighbors.")
    else:
        chart_neighbors = list(reversed(neighbors))
        neighbor_figure = go.Figure(
            go.Bar(
                x=[pair.jaccard for _, pair in chart_neighbors],
                y=[keyword for keyword, _ in chart_neighbors],
                orientation="h",
                customdata=[[pair.shared_count] for _, pair in chart_neighbors],
                hovertemplate=(
                    "%{y}<br>Jaccard: %{x:.2%}<br>"
                    "Shared URLs: %{customdata[0]}<extra></extra>"
                ),
            )
        )
        neighbor_figure.update_layout(
            title="20 strongest positive-overlap neighbors",
            xaxis={"title": "Jaccard similarity", "range": [0, 1], "tickformat": ".0%"},
            yaxis={"title": None},
            height=max(360, 28 * len(chart_neighbors)),
            margin={"l": 20, "r": 20, "t": 50, "b": 40},
        )
        st.plotly_chart(neighbor_figure, use_container_width=True)

    comparison_options = [
        keyword for keyword in eligible_keywords if keyword != inspected_keyword
    ]
    if comparison_options:
        strongest_keywords = [keyword for keyword, _ in neighbors]
        default_comparison = (
            strongest_keywords[0] if strongest_keywords else comparison_options[0]
        )
        compared_keyword = st.selectbox(
            "Compare with any other eligible keyword",
            comparison_options,
            index=comparison_options.index(default_comparison),
        )
        pair = get_pair(analysis, inspected_keyword, compared_keyword)
        pair_metrics = st.columns(4)
        pair_metrics[0].metric(
            f"{inspected_keyword} URLs",
            len(analysis.evidence[inspected_keyword].urls),
        )
        pair_metrics[1].metric(
            f"{compared_keyword} URLs",
            len(analysis.evidence[compared_keyword].urls),
        )
        pair_metrics[2].metric("Shared URLs", pair.shared_count)
        pair_metrics[3].metric("Jaccard", f"{pair.jaccard:.2%}")

        inspected_by_url = {}
        for result in analysis.evidence[inspected_keyword].results:
            inspected_by_url.setdefault(result.normalized_url, result)
        compared_by_url = {}
        for result in analysis.evidence[compared_keyword].results:
            compared_by_url.setdefault(result.normalized_url, result)
        shared_rows = []
        for normalized_url in pair.shared_urls:
            inspected_result = inspected_by_url[normalized_url]
            compared_result = compared_by_url[normalized_url]
            shared_rows.append(
                {
                    "normalized_url": normalized_url,
                    f"{inspected_keyword} rank": inspected_result.rank,
                    f"{inspected_keyword} title": inspected_result.title,
                    f"{inspected_keyword} URL": inspected_result.url,
                    f"{compared_keyword} rank": compared_result.rank,
                    f"{compared_keyword} title": compared_result.title,
                    f"{compared_keyword} URL": compared_result.url,
                }
            )
        st.subheader("Shared ranking URLs")
        if shared_rows:
            st.dataframe(pd.DataFrame(shared_rows), use_container_width=True, hide_index=True)
        else:
            st.info("These keywords have zero URL overlap.")

        st.subheader("Full saved ranking lists")
        ranking_columns = st.columns(2)
        with ranking_columns[0]:
            st.markdown(f"**{inspected_keyword}**")
            st.dataframe(
                pd.DataFrame(ranking_rows(analysis, inspected_keyword)),
                use_container_width=True,
                hide_index=True,
            )
        with ranking_columns[1]:
            st.markdown(f"**{compared_keyword}**")
            st.dataframe(
                pd.DataFrame(ranking_rows(analysis, compared_keyword)),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("A second eligible keyword is required for pair inspection.")

with distribution_tab:
    shared_counts = Counter(pair.shared_count for pair in analysis.pairs.values())
    distribution_df = pd.DataFrame(
        {
            "shared_urls": list(range(11)),
            "keyword_pairs": [shared_counts.get(count, 0) for count in range(11)],
        }
    )
    overlapping_pairs = sum(
        count for shared, count in shared_counts.items() if shared > 0
    )
    overlap_percentage = overlapping_pairs / pair_count if pair_count else 0
    st.metric("Pairs with any URL overlap", f"{overlap_percentage:.2%}")
    distribution_figure = px.bar(
        distribution_df,
        x="shared_urls",
        y="keyword_pairs",
        title="Unique keyword pairs by shared URL count",
        labels={"shared_urls": "Shared URLs", "keyword_pairs": "Keyword pairs"},
    )
    distribution_figure.update_xaxes(dtick=1)
    st.plotly_chart(distribution_figure, use_container_width=True)

    result_counts = result_count_distribution(analysis.evidence.values())
    result_count_df = pd.DataFrame(
        {
            "saved_results": list(result_counts),
            "keywords": list(result_counts.values()),
        }
    )
    result_figure = px.bar(
        result_count_df,
        x="saved_results",
        y="keywords",
        title="Keywords by usable saved result count",
        labels={"saved_results": "Saved results", "keywords": "Keywords"},
    )
    result_figure.update_xaxes(dtick=1)
    st.plotly_chart(result_figure, use_container_width=True)
