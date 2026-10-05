"""Plotly figure helpers for the overlap explorer."""

from __future__ import annotations

import math
import colorsys
import textwrap
from html import escape
from hashlib import sha256
from typing import Literal

import networkx as nx
import plotly.graph_objects as go

from topical_map.overlap import OverlapAnalysis, PairOverlap, get_pair
from topical_map.clustering import AnchorGroups


def heatmap_figure(
    analysis: OverlapAnalysis,
    keywords: list[str],
    metric: Literal["shared", "jaccard"],
) -> go.Figure:
    z_values: list[list[float | None]] = []
    custom_data: list[list[list[float] | None]] = []
    for keyword_y in keywords:
        z_row: list[float | None] = []
        custom_row: list[list[float] | None] = []
        for keyword_x in keywords:
            if keyword_x == keyword_y:
                z_row.append(None)
                custom_row.append(None)
                continue
            pair = get_pair(analysis, keyword_x, keyword_y)
            z_row.append(float(pair.shared_count) if metric == "shared" else pair.jaccard)
            custom_row.append(
                [
                    len(analysis.evidence[keyword_y].urls),
                    len(analysis.evidence[keyword_x].urls),
                    pair.shared_count,
                    pair.jaccard * 100,
                ]
            )
        z_values.append(z_row)
        custom_data.append(custom_row)

    shared_metric = metric == "shared"
    figure = go.Figure(
        go.Heatmap(
            x=keywords,
            y=keywords,
            z=z_values,
            customdata=custom_data,
            zmin=0,
            zmax=10 if shared_metric else 1,
            colorscale="Blues",
            colorbar={"title": "Shared URLs" if shared_metric else "Jaccard"},
            hoverongaps=False,
            hovertemplate=(
                "Keyword A: %{y}<br>"
                "Keyword B: %{x}<br>"
                "A usable URLs: %{customdata[0]:.0f}<br>"
                "B usable URLs: %{customdata[1]:.0f}<br>"
                "Shared URLs: %{customdata[2]:.0f}<br>"
                "Jaccard: %{customdata[3]:.2f}%<extra></extra>"
            ),
        )
    )
    show_labels = len(keywords) <= 50
    figure.update_layout(
        height=720,
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        xaxis={"showticklabels": show_labels},
        yaxis={"showticklabels": show_labels, "autorange": "reversed"},
    )
    return figure


def spring_layout(
    nodes: tuple[str, ...],
    weighted_edges: tuple[tuple[str, str, float], ...],
) -> dict[str, tuple[float, float]]:
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_weighted_edges_from(weighted_edges)
    components = sorted(
        nx.connected_components(graph),
        key=lambda component: (-len(component), min(component, key=str.casefold).casefold()),
    )
    grid_width = max(1, math.ceil(math.sqrt(len(components))))
    positions: dict[str, tuple[float, float]] = {}
    for index, component in enumerate(components):
        subgraph = graph.subgraph(component)
        local_positions = nx.spring_layout(subgraph, seed=42, weight="weight")
        offset_x = float(index % grid_width) * 3.0
        offset_y = -float(index // grid_width) * 3.0
        for keyword, coordinates in local_positions.items():
            positions[keyword] = (
                float(coordinates[0]) + offset_x,
                float(coordinates[1]) + offset_y,
            )
    return positions


def graph_figure(
    analysis: OverlapAnalysis,
    edges: tuple[PairOverlap, ...],
    positions: dict[str, tuple[float, float]],
    selected_keyword: str | None,
    groups: AnchorGroups,
    selected_anchor: str | None = None,
    group_view: bool = False,
) -> go.Figure:
    edge_batches = {}
    for edge in edges:
        anchor_a = groups.assignments[edge.keyword_a].best.anchor
        anchor_b = groups.assignments[edge.keyword_b].best.anchor
        touching = selected_anchor in (anchor_a, anchor_b)
        cross_group = anchor_a != anchor_b
        if selected_anchor:
            opacity, width = (0.65, 1.5) if touching else (0.06, 0.5)
        else:
            opacity, width = (0.12, 0.6) if group_view and cross_group else (0.45, 0.7)
        edge_x, edge_y = edge_batches.setdefault((opacity, width), ([], []))
        x0, y0 = positions[edge.keyword_a]
        x1, y1 = positions[edge.keyword_b]
        edge_x.extend((x0, x1, None))
        edge_y.extend((y0, y1, None))

    edge_traces = [go.Scatter(
        x=x, y=y, mode="lines",
        line={"width": width, "color": f"rgba(100, 116, 139, {opacity})"},
        hoverinfo="skip",
    ) for (opacity, width), (x, y) in sorted(edge_batches.items())]
    node_keywords = [keyword for keyword in analysis.keywords if keyword in positions]
    # Stable anchor-derived colors survive edge filtering and highlighting.
    group_colors = {}
    for anchor in groups.anchors:
        hue = int(sha256(anchor.encode()).hexdigest()[:8], 16) / 2**32
        rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.8)
        group_colors[anchor] = "rgb(%d,%d,%d)" % tuple(round(channel * 255) for channel in rgb)
    node_trace = go.Scatter(
        x=[positions[keyword][0] for keyword in node_keywords],
        y=[positions[keyword][1] for keyword in node_keywords],
        mode="markers",
        text=node_keywords,
        customdata=[
            [
                analysis.evidence[keyword].search_volume,
                len(analysis.evidence[keyword].urls),
                groups.assignments[keyword].best.anchor,
                groups.assignments[keyword].best.shared_count,
                groups.assignments[keyword].best.jaccard,
                "Anchor (self-overlap)" if keyword in groups.members else "Member",
            ]
            for keyword in node_keywords
        ],
        marker={
            "opacity": [
                1 if selected_anchor is None or groups.assignments[keyword].best.anchor == selected_anchor else 0.18
                for keyword in node_keywords
            ],
            "size": [12 if keyword in groups.members else 8 for keyword in node_keywords],
            "symbol": ["diamond" if keyword in groups.members else "circle" for keyword in node_keywords],
            "color": [
                group_colors[groups.assignments[keyword].best.anchor]
                for keyword in node_keywords
            ],
            "line": {
                "width": [3 if keyword == selected_keyword else 0.5 for keyword in node_keywords],
                "color": ["#111827" if keyword == selected_keyword else "white" for keyword in node_keywords],
            },
        },
        hovertemplate=(
            "%{text}<br>"
            "Search volume: %{customdata[0]}<br>"
            "Usable URLs: %{customdata[1]}<br>"
            "Group anchor: %{customdata[2]}<br>"
            "Shared URLs with anchor: %{customdata[3]}<br>"
            "Jaccard with anchor: %{customdata[4]:.2%}<br>"
            "%{customdata[5]}<extra></extra>"
        ),
    )
    figure = go.Figure([*edge_traces, node_trace])
    figure.update_layout(
        height=720,
        showlegend=False,
        hovermode="closest",
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        xaxis={"visible": False},
        yaxis={"visible": False},
        plot_bgcolor="white",
    )
    return figure


def group_layout(groups: AnchorGroups, hide_singletons: bool = True):
    """Pack fixed-size group areas into a deterministic four-column grid."""
    anchors = [a for a in groups.anchors if not hide_singletons or len(groups.members[a]) > 1]
    columns = min(4, max(1, len(anchors)))
    positions, centers = {}, {}
    for index, anchor in enumerate(anchors):
        cx, cy = (index % columns) * 4.0, -(index // columns) * 4.5
        centers[anchor] = (cx, cy)
        positions[anchor] = (cx, cy)
        members = [keyword for keyword in groups.members[anchor] if keyword != anchor]
        # Concentric rings keep large groups inside their allotted area.
        rings = max(1, math.ceil((math.sqrt(1 + 0.8 * len(members)) - 1) / 2))
        offset = 0
        for ring in range(1, rings + 1):
            count = min(10 * ring, len(members) - offset)
            radius = 1.2 * ring / rings
            for step, keyword in enumerate(members[offset:offset + count]):
                angle = 2 * math.pi * step / count - math.pi / 2
                positions[keyword] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            offset += count
    return positions, centers, columns


def group_view_edges(analysis, groups, positions, display_edges, show_cross_group):
    """Always draw anchor spokes; optionally add filtered cross-group overlaps."""
    edges = {}
    for keyword in positions:
        anchor = groups.assignments[keyword].best.anchor
        if keyword != anchor:
            pair = get_pair(analysis, keyword, anchor)
            edges[(pair.keyword_a, pair.keyword_b)] = pair
    if show_cross_group:
        for pair in display_edges:
            if (pair.keyword_a in positions and pair.keyword_b in positions
                    and groups.assignments[pair.keyword_a].best.anchor != groups.assignments[pair.keyword_b].best.anchor):
                edges[(pair.keyword_a, pair.keyword_b)] = pair
    return tuple(edges.values())


def group_figure(analysis, groups, positions, centers, columns, edges, selected_keyword, selected_anchor):
    figure = graph_figure(analysis, edges, positions, selected_keyword, groups, selected_anchor, group_view=True)
    for anchor, (cx, cy) in centers.items():
        selected = selected_anchor == anchor
        figure.add_shape(
            type="rect", x0=cx - 1.8, x1=cx + 1.8, y0=cy - 1.6, y1=cy + 2.6,
            line={"color": "#2563eb" if selected else "#e2e8f0", "width": 2 if selected else 1},
            fillcolor="#f8fafc", layer="below",
        )
        label = "<br>".join(escape(line) for line in textwrap.wrap(anchor, width=26))
        figure.add_annotation(
            x=cx, y=cy + 2.45, text=f"{label}<br><b>{len(groups.members[anchor])} keywords</b>",
            showarrow=False, yanchor="top", font={"size": 12, "color": "#334155"},
            opacity=1 if selected_anchor is None or selected else 0.35,
        )
    rows = max(1, math.ceil(len(centers) / columns))
    figure.update_layout(
        height=max(320, rows * 270),
        xaxis={"range": [-2, (columns - 1) * 4 + 2]},
        yaxis={"range": [-(rows - 1) * 4.5 - 1.85, 2.85]},
        uirevision="group-grid-" + "|".join(centers),
    )
    return figure
