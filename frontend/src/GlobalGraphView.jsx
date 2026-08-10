import React, { useState, useEffect, useMemo, useRef } from 'react';
import axios from 'axios';
import ForceGraph2D from 'react-force-graph-2d';

const API_BASE = '/api';

export default function GlobalGraphView({ onBack }) {
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [topicFilter, setTopicFilter] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);
  const fgRef = useRef();
  const containerRef = useRef();
  const [dims, setDims] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(entries => {
      for (let e of entries) {
        setDims({ width: e.contentRect.width, height: e.contentRect.height });
      }
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const fetchGraph = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`${API_BASE}/graph`);
      setGraphData(response.data);
    } catch (err) {
      if (err.response?.status === 401) {
        setError('Please log in to view your Knowledge Graph.');
      } else {
        setError('Failed to load your Knowledge Graph. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchGraph(); }, []);

  const filteredGraph = useMemo(() => {
    const q = topicFilter.trim().toLowerCase();
    if (!q) return graphData;
    const matchedIds = new Set(
      (graphData.nodes || []).filter(n =>
        n.label?.toLowerCase().includes(q) || n.description?.toLowerCase().includes(q)
      ).map(n => String(n.id))
    );
    const filteredNodes = (graphData.nodes || []).filter(n => matchedIds.has(String(n.id)));
    const filteredEdges = (graphData.edges || []).filter(e =>
      matchedIds.has(String(e.from_concept_id)) && matchedIds.has(String(e.to_concept_id))
    );
    return { nodes: filteredNodes, edges: filteredEdges };
  }, [graphData, topicFilter]);

  const mastered = (graphData.nodes || []).filter(n => n.mastery_score >= 70).length;
  const learning = (graphData.nodes || []).filter(n => n.mastery_score >= 30 && n.mastery_score < 70).length;
  const review = (graphData.nodes || []).filter(n => (n.mastery_score ?? 0) < 30).length;

  const graphPayload = useMemo(() => {
    if (!filteredGraph?.nodes) return { nodes: [], links: [] };
    const nodes = filteredGraph.nodes.map(n => ({
      id: String(n.id),
      name: n.label,
      mastery: n.mastery_score ?? 0,
      description: n.description,
      timestamp: n.timestamp_seconds,
      rawMastery: n.mastery_score,
    }));
    const links = (filteredGraph.edges || []).map(e => ({
      source: String(e.from_concept_id ?? e.source_id),
      target: String(e.to_concept_id ?? e.target_id),
      label: e.relationship_type ?? e.relationship,
    }));
    return { nodes, links };
  }, [filteredGraph]);

  useEffect(() => {
    if (fgRef.current && graphPayload.nodes.length > 0) {
      const fg = fgRef.current;
      fg.d3Force('charge')?.strength(-350);
      fg.d3Force('link')?.distance(120);
    }
  }, [graphPayload]);

  const handleNodeClick = (node) => {
    setSelectedNode(node);
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 800);
      fgRef.current.zoom(3, 800);
    }
  };

  const getMasteryColor = (score) => {
    if (score == null || score < 30) return '#ef4444';
    if (score < 70) return '#eab308';
    return '#22c55e';
  };

  const getMasteryLabel = (score) => {
    if (score == null || score < 30) return 'Review';
    if (score < 70) return 'Learning';
    return 'Mastered';
  };

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #F0F4FF 0%, #E8F4FD 100%)', fontFamily: "'Plus Jakarta Sans', Inter, sans-serif", position: 'relative', display: 'flex', flexDirection: 'column' }}>
      {/* Background orbs */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 0, overflow: 'hidden', pointerEvents: 'none' }}>
        <div style={{ position: 'absolute', width: 600, height: 600, borderRadius: '50%', filter: 'blur(100px)', opacity: 0.15, background: 'linear-gradient(135deg, #4F46E5, #818CF8)', top: -200, left: -100 }} />
        <div style={{ position: 'absolute', width: 400, height: 400, borderRadius: '50%', filter: 'blur(80px)', opacity: 0.12, background: 'linear-gradient(135deg, #06B6D4, #22D3EE)', bottom: -100, right: -50 }} />
      </div>

      {/* Sticky Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem 1.25rem', borderBottom: '1px solid rgba(255,255,255,0.6)', background: 'rgba(248,250,252,0.9)', backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)', position: 'sticky', top: 0, zIndex: 10, flexWrap: 'wrap', gap: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button onClick={onBack} style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', color: '#475569', padding: '0.45rem 0.9rem', borderRadius: '10px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem', boxShadow: '0 2px 4px rgba(0,0,0,0.04)' }}>
            ← Back
          </button>
          <div>
            <h1 style={{ margin: 0, fontSize: 'clamp(1rem, 3vw, 1.35rem)', fontWeight: 800, color: '#0F172A', lineHeight: 1.2 }}>My Knowledge Graph</h1>
            <p style={{ margin: 0, fontSize: '0.75rem', color: '#64748B', marginTop: '2px', fontWeight: 500 }}>Accumulated concepts across all your studied videos</p>
          </div>
        </div>

        {!loading && !error && graphData.nodes.length > 0 && (
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <StatBadge color="#22c55e" bg="#F0FDF4" borderColor="#BBF7D0" label="Mastered" count={mastered} />
            <StatBadge color="#F59E0B" bg="#FFFBEB" borderColor="#FDE68A" label="Learning" count={learning} />
            <StatBadge color="#EF4444" bg="#FEF2F2" borderColor="#FECACA" label="Review" count={review} />
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div style={{ padding: '0.85rem 1.25rem', background: 'rgba(248,250,252,0.6)', borderBottom: '1px solid #F1F5F9', position: 'relative', zIndex: 1 }}>
        <div style={{ position: 'relative', maxWidth: '380px' }}>
          <span style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', fontSize: '0.9rem', pointerEvents: 'none', color: '#94A3B8' }}>🔍</span>
          <input
            type="text"
            placeholder="Filter by topic or concept…"
            value={topicFilter}
            onChange={e => setTopicFilter(e.target.value)}
            style={{ width: '100%', padding: '0.6rem 1rem 0.6rem 2.3rem', background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '10px', color: '#0F172A', fontSize: '0.875rem', outline: 'none', fontFamily: 'inherit', fontWeight: 500, boxSizing: 'border-box' }}
          />
        </div>
        {topicFilter && (
          <span style={{ marginTop: '0.4rem', display: 'block', color: '#64748B', fontSize: '0.75rem', fontWeight: 500 }}>
            Showing {filteredGraph.nodes.length} of {graphData.nodes.length} concepts
          </span>
        )}
      </div>

      {/* Main: graph + node panel */}
      <div style={{ display: 'flex', flex: 1, position: 'relative', zIndex: 1, overflow: 'hidden', minHeight: '0' }}>
        {/* Graph canvas */}
        <div ref={containerRef} style={{ flex: 1, position: 'relative', minHeight: '500px' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: '1rem', color: '#64748B' }}>
              <div style={{ width: 40, height: 40, border: '3px solid #E2E8F0', borderTop: '3px solid #4F46E5', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
              <p style={{ fontWeight: 600 }}>Building your knowledge graph…</p>
            </div>
          )}
          {error && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#ef4444', fontWeight: 600, textAlign: 'center', padding: '2rem' }}>
              {error}
            </div>
          )}
          {!loading && !error && (
            <ForceGraph2D
              ref={fgRef}
              width={dims.width || 800}
              height={dims.height || 600}
              graphData={graphPayload}
              nodeLabel={node => node.description || node.name}
              nodeRelSize={7}
              linkColor={() => 'rgba(99, 102, 241, 0.35)'}
              linkWidth={1.5}
              linkDirectionalParticles={2}
              linkDirectionalParticleSpeed={0.004}
              onNodeClick={handleNodeClick}
              backgroundColor="#F8FAFC"
              nodeCanvasObject={(node, ctx, globalScale) => {
                const label = node.name;
                const fontSize = Math.max(12, 14 / globalScale);
                ctx.font = `bold ${fontSize}px "SF Pro Display", "Inter", sans-serif`;
                const textWidth = ctx.measureText(label).width;
                const padX = fontSize * 0.8;
                const padY = fontSize * 0.55;
                const bw = textWidth + padX * 2;
                const bh = fontSize + padY * 2;
                const bx = node.x - bw / 2;
                const by = node.y - bh / 2;
                const r = bh / 2;
                const masteryColor = getMasteryColor(node.mastery);
                const isSelected = selectedNode?.id === node.id;

                // Shadow
                ctx.shadowColor = isSelected ? masteryColor : 'rgba(0,0,0,0.12)';
                ctx.shadowBlur = isSelected ? 18 : 8;

                // Pill background
                ctx.beginPath();
                ctx.moveTo(bx + r, by);
                ctx.lineTo(bx + bw - r, by);
                ctx.quadraticCurveTo(bx + bw, by, bx + bw, by + r);
                ctx.lineTo(bx + bw, by + bh - r);
                ctx.quadraticCurveTo(bx + bw, by + bh, bx + bw - r, by + bh);
                ctx.lineTo(bx + r, by + bh);
                ctx.quadraticCurveTo(bx, by + bh, bx, by + bh - r);
                ctx.lineTo(bx, by + r);
                ctx.quadraticCurveTo(bx, by, bx + r, by);
                ctx.closePath();
                ctx.fillStyle = isSelected ? 'rgba(79, 70, 229, 0.08)' : 'rgba(255, 255, 255, 0.95)';
                ctx.fill();

                // Border
                ctx.strokeStyle = isSelected ? '#4F46E5' : masteryColor;
                ctx.lineWidth = (isSelected ? 2 : 1.5) / globalScale;
                ctx.stroke();
                ctx.shadowBlur = 0;

                // Label
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = isSelected ? '#4F46E5' : '#1E293B';
                ctx.fillText(label, node.x, node.y);

                node.__bckgDimensions = [bw, bh];
              }}
              nodePointerAreaPaint={(node, color, ctx) => {
                ctx.fillStyle = color;
                const [bw, bh] = node.__bckgDimensions || [40, 20];
                ctx.fillRect(node.x - bw / 2, node.y - bh / 2, bw, bh);
              }}
            />
          )}
        </div>

        {/* Node Info Panel */}
        {selectedNode && (
          <div style={{ width: '260px', minWidth: '220px', background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(20px)', borderLeft: '1px solid #E2E8F0', padding: '1.5rem', boxShadow: '-4px 0 24px rgba(0,0,0,0.06)', overflowY: 'auto', position: 'relative', zIndex: 2, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <button onClick={() => setSelectedNode(null)} style={{ position: 'absolute', top: '1rem', right: '1rem', background: 'transparent', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '4px', display: 'flex' }}>✕</button>
            <div style={{ paddingTop: '0.5rem' }}>
              <div style={{ width: '36px', height: '4px', borderRadius: '2px', background: getMasteryColor(selectedNode.mastery), marginBottom: '1rem' }} />
              <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', fontWeight: 800, color: '#0F172A', lineHeight: 1.2 }}>{selectedNode.name}</h3>
              <span style={{ fontSize: '0.7rem', fontWeight: 700, padding: '3px 10px', borderRadius: '20px', background: getMasteryColor(selectedNode.mastery) + '22', color: getMasteryColor(selectedNode.mastery), border: `1px solid ${getMasteryColor(selectedNode.mastery)}44`, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {getMasteryLabel(selectedNode.mastery)}
              </span>
            </div>
            {selectedNode.description && (
              <div>
                <p style={{ margin: 0, fontSize: '0.85rem', color: '#475569', lineHeight: 1.6 }}>{selectedNode.description}</p>
              </div>
            )}
            {selectedNode.timestamp > 0 && (
              <div style={{ background: '#F8FAFC', borderRadius: '10px', padding: '0.75rem 1rem', border: '1px solid #E2E8F0' }}>
                <p style={{ margin: 0, fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>VIDEO TIMESTAMP</p>
                <p style={{ margin: '4px 0 0', fontSize: '1rem', fontWeight: 700, color: '#4F46E5' }}>
                  ⏱ {Math.floor(selectedNode.timestamp / 60)}:{String(selectedNode.timestamp % 60).padStart(2, '0')}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Refresh button */}
      {!loading && (
        <div style={{ textAlign: 'center', padding: '0.75rem 1.25rem 1.5rem', position: 'relative', zIndex: 1 }}>
          <button onClick={fetchGraph} style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', color: '#475569', padding: '0.5rem 1.25rem', borderRadius: '10px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600, boxShadow: '0 2px 4px rgba(0,0,0,0.04)', fontFamily: 'inherit' }}>
            ↻ Refresh Graph
          </button>
        </div>
      )}
    </div>
  );
}

function StatBadge({ color, bg, borderColor, label, count }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 700, background: bg, border: `1px solid ${borderColor}`, padding: '0.25rem 0.65rem', borderRadius: '20px' }}>
      <div style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
      <span style={{ color: '#374151' }}>{count} {label}</span>
    </div>
  );
}
