"""
Generate CiteSpace-style knowledge distribution visualization.

Creates a publication-quality network visualization with:
- Node sizes based on importance (number of rules/connections)
- Concentric colored rings showing categories
- Labels sized by importance
- Force-directed clustering layout
"""

import asyncio
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from transportations_validator.db.postgres import async_session_maker
from transportations_validator.db.postgres.repositories import (
    ParameterRepository,
    RuleRepository,
)

OUTPUT_DIR = Path(__file__).parent.parent / "static"


async def fetch_data():
    """Fetch parameters and rules from database."""
    async with async_session_maker() as session:
        param_repo = ParameterRepository(session)
        rule_repo = RuleRepository(session)
        parameters = await param_repo.get_all()
        rules = await rule_repo.get_all()
        return parameters, rules


def create_citespace_graph(parameters, rules):
    """Create a NetworkX graph from parameters and rules."""
    graph = nx.Graph()

    # Count rules per parameter for sizing
    rule_counts = defaultdict(int)
    for rule in rules:
        if rule.parameter_id:
            rule_counts[rule.parameter_id] += 1

    # Add parameter nodes
    for param in parameters:
        facility = param.facility_type.value if param.facility_type else "Unknown"
        graph.add_node(
            f"p_{param.id}",
            label=param.rust_field,
            name=param.name,
            node_type="parameter",
            facility=facility,
            rule_count=rule_counts.get(param.id, 0),
            unit=param.unit or "",
        )

    # Add rule nodes (smaller)
    severity_order = {"error": 3, "warning": 2, "info": 1}
    for rule in rules:
        severity = rule.severity.value if rule.severity else "info"
        graph.add_node(
            f"r_{rule.id}",
            label=rule.name[:15] + "..." if len(rule.name) > 15 else rule.name,
            name=rule.name,
            node_type="rule",
            severity=severity,
            severity_weight=severity_order.get(severity, 1),
            rule_type=rule.rule_type.value if rule.rule_type else "unknown",
        )

        # Add edge to parameter
        if rule.parameter_id:
            param_node = f"p_{rule.parameter_id}"
            if param_node in graph:
                graph.add_edge(f"r_{rule.id}", param_node, weight=1)

    # Add edges between parameters of same facility (implicit relationships)
    param_nodes = [n for n in graph.nodes() if graph.nodes[n].get("node_type") == "parameter"]
    for i, p1 in enumerate(param_nodes):
        for p2 in param_nodes[i + 1 :]:
            if graph.nodes[p1]["facility"] == graph.nodes[p2]["facility"]:
                # Light connection between same-facility parameters
                graph.add_edge(p1, p2, weight=0.3)

    return graph


def draw_citespace_visualization(
    graph,
    output_path: Path,
    title: str = "CrossTraffic Knowledge Distribution",
    figsize: tuple = (20, 16),
):
    """Draw CiteSpace-style visualization."""
    fig, ax = plt.subplots(figsize=figsize, facecolor="white")
    ax.set_facecolor("white")

    # Color schemes - darker colors for white background
    facility_colors = {
        "BasicFreeway": "#E53935",  # Red
        "MultilaneHighway": "#00897B",  # Teal
        "TwoLaneHighway": "#FF8F00",  # Orange/Amber
        "UrbanStreet": "#43A047",  # Green
        "Unknown": "#757575",  # Grey
    }

    severity_colors = {
        "error": "#D32F2F",
        "warning": "#F57C00",
        "info": "#388E3C",
    }

    # Create layout - dense, no center gravity
    print("Computing layout...")
    # Use smaller k value for denser layout, more iterations
    pos = nx.spring_layout(
        graph,
        k=0.8 / math.sqrt(len(graph.nodes())),  # Smaller k = denser
        iterations=200,
        seed=42,
        weight="weight",
        center=None,  # No center gravity
        scale=2.0,  # Spread across larger area
    )

    # Separate nodes by type
    param_nodes = [n for n in graph.nodes() if graph.nodes[n].get("node_type") == "parameter"]
    rule_nodes = [n for n in graph.nodes() if graph.nodes[n].get("node_type") == "rule"]

    # Draw edges first (background)
    print("Drawing edges...")
    edge_colors = []
    edge_widths = []
    for u, v in graph.edges():
        weight = graph.edges[u, v].get("weight", 1)
        edge_colors.append("#BDBDBD")  # Light grey for white background
        edge_widths.append(0.4 * weight)

    nx.draw_networkx_edges(
        graph,
        pos,
        alpha=0.3,
        edge_color=edge_colors,
        width=edge_widths,
        ax=ax,
    )

    # Draw rule nodes (smaller, in background)
    print("Drawing rule nodes...")
    for node in rule_nodes:
        x, y = pos[node]
        severity = graph.nodes[node].get("severity", "info")
        color = severity_colors.get(severity, "#888888")
        label = graph.nodes[node].get("label", "")

        # Small circle for rules
        circle = plt.Circle(
            (x, y),
            0.02,
            color=color,
            alpha=0.6,
            zorder=2,
        )
        ax.add_patch(circle)

        # Label for rule nodes - smaller font
        ax.annotate(
            label,
            (x, y + 0.03),  # Position above node
            fontsize=5,
            color="#666666",
            ha="center",
            va="bottom",
            zorder=3,
        )

    # Draw parameter nodes with concentric rings (CiteSpace style)
    print("Drawing parameter nodes...")
    max_rules = max((graph.nodes[n].get("rule_count", 1) for n in param_nodes), default=1)

    for node in param_nodes:
        x, y = pos[node]
        facility = graph.nodes[node].get("facility", "Unknown")
        rule_count = graph.nodes[node].get("rule_count", 1)
        label = graph.nodes[node].get("label", "")

        # Base size scaled by rule count
        base_size = 0.03 + (rule_count / max_rules) * 0.08
        color = facility_colors.get(facility, "#888888")

        # Draw concentric rings (outer to inner)
        num_rings = min(3 + rule_count // 2, 6)
        for i in range(num_rings, 0, -1):
            ring_size = base_size * (i / num_rings)
            alpha = 0.3 + (0.5 * (num_rings - i) / num_rings)

            circle = plt.Circle(
                (x, y),
                ring_size,
                color=color,
                alpha=alpha,
                zorder=3 + i,
            )
            ax.add_patch(circle)

        # Inner bright core - use facility color with white center dot
        core = plt.Circle(
            (x, y),
            base_size * 0.3,
            color=color,
            alpha=0.9,
            zorder=10,
        )
        ax.add_patch(core)

        # Label - size based on importance, dark text for white background
        font_size = 6 + (rule_count / max_rules) * 10
        ax.annotate(
            label,
            (x, y + base_size + 0.02),  # Position label above node
            fontsize=font_size,
            color="#333333",
            ha="center",
            va="bottom",
            fontweight="bold" if rule_count > max_rules / 2 else "normal",
            zorder=15,
        )

    # Add title
    ax.set_title(
        title,
        fontsize=24,
        color="#333333",
        fontweight="bold",
        pad=20,
    )

    # Add legend
    legend_elements = [
        mpatches.Patch(color=c, label=f, alpha=0.7)
        for f, c in facility_colors.items()
        if f != "Unknown"
    ]
    legend_elements.append(mpatches.Patch(color="#888888", label="Unknown", alpha=0.7))

    # Severity legend
    legend_elements.extend(
        [
            mpatches.Patch(color="#FF4757", label="Error Rule", alpha=0.6),
            mpatches.Patch(color="#FFA502", label="Warning Rule", alpha=0.6),
            mpatches.Patch(color="#2ED573", label="Info Rule", alpha=0.6),
        ]
    )

    ax.legend(
        handles=legend_elements,
        loc="upper left",
        facecolor="white",
        edgecolor="#CCCCCC",
        labelcolor="#333333",
        fontsize=10,
    )

    # Add stats
    stats_text = (
        f"Parameters: {len(param_nodes)} | Rules: {len(rule_nodes)} | Edges: {len(graph.edges())}"
    )
    ax.text(
        0.99,
        0.01,
        stats_text,
        transform=ax.transAxes,
        fontsize=10,
        color="#888888",
        ha="right",
        va="bottom",
    )

    # Remove axes - wider limits for scale=2.0 layout
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(-2.5, 2.5)
    ax.axis("off")

    plt.tight_layout()

    # Save
    print(f"Saving to {output_path}...")
    plt.savefig(
        output_path,
        dpi=150,
        facecolor="white",
        edgecolor="none",
        bbox_inches="tight",
    )
    plt.close()

    return output_path


def draw_facility_focused_visualization(
    graph,
    output_path: Path,
    figsize: tuple = (24, 18),
):
    """Draw a facility-type focused visualization with clusters."""
    fig, ax = plt.subplots(figsize=figsize, facecolor="white")
    ax.set_facecolor("white")

    # Darker colors for white background
    facility_colors = {
        "BasicFreeway": "#E53935",  # Red
        "MultilaneHighway": "#00897B",  # Teal
        "TwoLaneHighway": "#FF8F00",  # Orange/Amber
        "UrbanStreet": "#43A047",  # Green
        "Unknown": "#757575",  # Grey
    }

    # Group parameters by facility
    param_nodes = [n for n in graph.nodes() if graph.nodes[n].get("node_type") == "parameter"]
    facility_groups = defaultdict(list)
    for node in param_nodes:
        facility = graph.nodes[node].get("facility", "Unknown")
        facility_groups[facility].append(node)

    # Create clustered layout
    print("Computing clustered layout...")
    pos = {}

    # Position facility clusters in a circle
    num_facilities = len(facility_groups)
    for i, (facility, nodes) in enumerate(facility_groups.items()):
        # Cluster center
        angle = 2 * math.pi * i / num_facilities
        cx, cy = math.cos(angle) * 0.6, math.sin(angle) * 0.6

        # Position nodes within cluster
        if len(nodes) == 1:
            pos[nodes[0]] = (cx, cy)
        else:
            for j, node in enumerate(nodes):
                inner_angle = 2 * math.pi * j / len(nodes)
                radius = 0.15 + (j % 3) * 0.05
                x = cx + math.cos(inner_angle) * radius
                y = cy + math.sin(inner_angle) * radius
                pos[node] = (x, y)

    # Position rule nodes near their parameters
    rule_nodes = [n for n in graph.nodes() if graph.nodes[n].get("node_type") == "rule"]
    for node in rule_nodes:
        neighbors = list(graph.neighbors(node))
        if neighbors and neighbors[0] in pos:
            px, py = pos[neighbors[0]]
            # Offset slightly
            offset = np.random.uniform(-0.08, 0.08, 2)
            pos[node] = (px + offset[0], py + offset[1])
        else:
            pos[node] = (np.random.uniform(-1, 1), np.random.uniform(-1, 1))

    # Draw edges
    print("Drawing edges...")
    nx.draw_networkx_edges(
        graph,
        pos,
        alpha=0.2,
        edge_color="#BDBDBD",
        width=0.5,
        ax=ax,
    )

    # Draw facility cluster backgrounds
    for facility, nodes in facility_groups.items():
        if not nodes:
            continue
        xs = [pos[n][0] for n in nodes]
        ys = [pos[n][1] for n in nodes]
        cx, cy = np.mean(xs), np.mean(ys)
        radius = max(0.2, max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 0.1)

        color = facility_colors.get(facility, "#888888")
        circle = plt.Circle(
            (cx, cy),
            radius,
            color=color,
            alpha=0.1,
            zorder=1,
        )
        ax.add_patch(circle)

        # Facility label
        ax.text(
            cx,
            cy + radius + 0.05,
            facility,
            fontsize=14,
            color=color,
            ha="center",
            va="bottom",
            fontweight="bold",
        )

    # Draw rule nodes
    for node in rule_nodes:
        if node not in pos:
            continue
        x, y = pos[node]
        severity = graph.nodes[node].get("severity", "info")
        label = graph.nodes[node].get("label", "")
        colors = {"error": "#FF4757", "warning": "#FFA502", "info": "#2ED573"}
        color = colors.get(severity, "#888888")

        circle = plt.Circle((x, y), 0.015, color=color, alpha=0.5, zorder=2)
        ax.add_patch(circle)

        # Label for rule nodes - smaller font
        ax.annotate(
            label,
            (x, y + 0.025),  # Position above node
            fontsize=5,
            color="#666666",
            ha="center",
            va="bottom",
            zorder=3,
        )

    # Draw parameter nodes
    max_rules = max((graph.nodes[n].get("rule_count", 1) for n in param_nodes), default=1)

    for node in param_nodes:
        x, y = pos[node]
        facility = graph.nodes[node].get("facility", "Unknown")
        rule_count = graph.nodes[node].get("rule_count", 1)
        label = graph.nodes[node].get("label", "")
        color = facility_colors.get(facility, "#888888")

        # Size based on rule count
        base_size = 0.025 + (rule_count / max_rules) * 0.06

        # Concentric rings
        for i in range(4, 0, -1):
            ring_size = base_size * (i / 4)
            alpha = 0.2 + 0.6 * (4 - i) / 4
            circle = plt.Circle((x, y), ring_size, color=color, alpha=alpha, zorder=3 + i)
            ax.add_patch(circle)

        # Core
        core = plt.Circle((x, y), base_size * 0.25, color=color, alpha=0.9, zorder=10)
        ax.add_patch(core)

        # Label - dark text for white background
        font_size = 7 + (rule_count / max_rules) * 8
        ax.annotate(
            label,
            (x, y + base_size + 0.02),  # Position above node
            fontsize=font_size,
            color="#333333",
            ha="center",
            va="bottom",
            fontweight="bold" if rule_count > 2 else "normal",
            zorder=15,
        )

    # Title and legend
    ax.set_title(
        "CrossTraffic Knowledge Distribution by Facility Type",
        fontsize=20,
        color="#333333",
        fontweight="bold",
        pad=20,
    )

    legend_elements = [
        mpatches.Patch(color=c, label=f, alpha=0.7) for f, c in facility_colors.items()
    ]
    ax.legend(
        handles=legend_elements,
        loc="upper right",
        facecolor="white",
        edgecolor="#CCCCCC",
        labelcolor="#333333",
        fontsize=10,
    )

    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    ax.axis("off")
    plt.tight_layout()

    print(f"Saving to {output_path}...")
    plt.savefig(output_path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close()

    return output_path


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate CiteSpace-style visualization")
    parser.add_argument("--output", "-o", type=str, help="Output file path")
    parser.add_argument(
        "--style",
        choices=["spring", "clustered", "both"],
        default="both",
        help="Visualization style",
    )
    parser.add_argument("--open", action="store_true", help="Open after generating")

    args = parser.parse_args()

    print("Fetching data...")
    parameters, rules = await fetch_data()
    print(f"Found {len(parameters)} parameters and {len(rules)} rules")

    print("Building graph...")
    graph = create_citespace_graph(parameters, rules)
    print(f"Graph has {len(graph.nodes())} nodes and {len(graph.edges())} edges")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs = []

    if args.style in ("spring", "both"):
        output_path = Path(args.output) if args.output else OUTPUT_DIR / "knowledge_citespace.png"
        draw_citespace_visualization(graph, output_path)
        outputs.append(output_path)
        print(f"Spring layout saved to: {output_path}")

    if args.style in ("clustered", "both"):
        output_path = OUTPUT_DIR / "knowledge_clustered.png"
        draw_facility_focused_visualization(graph, output_path)
        outputs.append(output_path)
        print(f"Clustered layout saved to: {output_path}")

    if args.open and outputs:
        import webbrowser

        for path in outputs:
            webbrowser.open(f"file://{path.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
