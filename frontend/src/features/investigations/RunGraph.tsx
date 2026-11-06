"use client";

import { Background, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphNode } from "@/lib/types";

const STATE_STYLE: Record<GraphNode["state"], { bg: string; border: string; color: string; label: string }> = {
  pending: { bg: "#fffdf9", border: "#d4c9b7", color: "#5a6371", label: "pending" },
  active: { bg: "#ecf7f5", border: "#0f7f76", color: "#0e6b64", label: "running" },
  completed: { bg: "#e9f6ec", border: "#23703a", color: "#23703a", label: "done" },
  waiting: { bg: "#fdf6e7", border: "#9a5a07", color: "#9a5a07", label: "awaiting review" },
  failed: { bg: "#fdeeec", border: "#a3261b", color: "#a3261b", label: "failed" },
  cancelled: { bg: "#f1efe9", border: "#a9b6c9", color: "#5a6371", label: "cancelled" },
};

/** Node states come only from persisted runtime events (see API graph_view). */
export function RunGraph({ graph }: { graph: GraphNode[] }) {
  const nodes: Node[] = graph.map((g, i) => {
    const s = STATE_STYLE[g.state];
    return {
      id: g.id,
      position: { x: 0, y: i * 64 },
      data: { label: `${g.label}${g.turns ? ` · ${g.turns} turn${g.turns > 1 ? "s" : ""}` : ""} — ${s.label}` },
      draggable: false,
      connectable: false,
      style: { background: s.bg, border: `1.5px solid ${s.border}`, color: s.color, fontSize: 12, width: 230, borderRadius: 6, padding: 6 },
      ariaLabel: `${g.label}: ${s.label}`,
    };
  });
  const edges: Edge[] = graph.slice(1).map((g, i) => ({
    id: `${graph[i].id}-${g.id}`,
    source: graph[i].id,
    target: g.id,
    style: { stroke: "#d4c9b7" },
  }));
  edges.push({ id: "loop", source: "investigate", target: "investigate", type: "default", style: { stroke: "#d4c9b7" } });
  return (
    <div className="h-[600px] w-full" role="img" aria-label="Investigation graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll={false}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} color="#efe8dc" />
      </ReactFlow>
      <ul className="sr-only">
        {graph.map((g) => <li key={g.id}>{g.label}: {STATE_STYLE[g.state].label}</li>)}
      </ul>
    </div>
  );
}
