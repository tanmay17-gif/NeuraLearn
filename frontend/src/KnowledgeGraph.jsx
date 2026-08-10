import React, { useRef, useMemo, useEffect, useState, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

/**
 * KnowledgeGraph (Force-Directed)
 *
 * Props:
 *   graphData  — { nodes: [...], edges: [...] }  (from API)
 *   onNodeClick — (timestamp_seconds: number) => void
 *   loading    — boolean
 *   error      — string | null
 */
export default function KnowledgeGraph({ graphData, onNodeClick, loading = false, error = null }) {
  const fgRef = useRef();
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height
        });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const graphPayload = useMemo(() => {
    if (!graphData?.nodes) return { nodes: [], links: [] };

    const nodes = graphData.nodes.map(n => ({
      id: String(n.id),
      name: n.label,
      val: 1,
      mastery: n.mastery_score,
      timestamp: n.timestamp_seconds,
      description: n.description
    }));

    const links = (graphData.edges || []).map(e => ({
      source: String(e.source_id || e.from_concept_id),
      target: String(e.target_id || e.to_concept_id),
      label: e.relationship || e.relationship_type
    }));

    return { nodes, links };
  }, [graphData]);

  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3Force('charge').strength(-400);
      fgRef.current.d3Force('link').distance(100);
    }
  }, [graphPayload]);

  const handleNodeClick = useCallback(node => {
    fgRef.current.centerAt(node.x, node.y, 1000);
    fgRef.current.zoom(2.5, 1000);
    
    if (onNodeClick && node.timestamp > 0) {
      onNodeClick(node.timestamp);
    }
  }, [onNodeClick]);

  if (loading) {
    return (
      <div style={containerStyle}>
        <div style={centeredStyle}>
          <div style={spinnerStyle} />
          <p style={{ color: '#475569', marginTop: '1rem', fontSize: '0.9rem', fontWeight: 500 }}>
            Building your Knowledge Graph…
          </p>
        </div>
      </div>
    );
  }

  // ── Error state ─────────────────────────────────────────────────────────
  if (error) {
    return (
      <div style={containerStyle}>
        <div style={centeredStyle}>
          <div style={{ fontSize: '2rem', marginBottom: '0.75rem' }}>⚠️</div>
          <p style={{ color: '#f87171', fontWeight: 600 }}>{error}</p>
        </div>
      </div>
    );
  }

  // ── Empty state ─────────────────────────────────────────────────────────
  if (!graphData?.nodes?.length) {
    return (
      <div style={containerStyle}>
        <div style={centeredStyle}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🧠</div>
          <h3 style={{ color: '#0F172A', fontWeight: 800, marginBottom: '0.5rem' }}>
            No concepts yet
          </h3>
          <p style={{ color: '#475569', fontSize: '0.95rem', maxWidth: '280px', textAlign: 'center', lineHeight: 1.5 }}>
            Process a video and open the Concept Map tab — your graph will appear here.
          </p>
        </div>
      </div>
    );
  }

  // ── Graph ───────────────────────────────────────────────────────────────
  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: '600px', background: '#F8FAFC' }}>
      <ForceGraph2D
        ref={fgRef}
        width={dimensions.width || 800}
        height={dimensions.height || 600}
        graphData={graphPayload}
        nodeLabel="description"
        nodeColor={node => {
          if (node.mastery < 30) return '#ef4444';
          if (node.mastery < 70) return '#eab308';
          return '#22c55e';
        }}
        nodeRelSize={8}
        linkColor={() => 'rgba(99, 102, 241, 0.4)'}
        linkWidth={2}
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.005}
        onNodeClick={handleNodeClick}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.name;
          const fontSize = 14 / globalScale;
          ctx.font = `bold ${fontSize}px "SF Pro Display", "Inter", Sans-Serif`;
          const textWidth = ctx.measureText(label).width;
          const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 1.5); // padding

          ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
          ctx.beginPath();
          ctx.roundRect(
            node.x - bckgDimensions[0] / 2, 
            node.y - bckgDimensions[1] / 2, 
            bckgDimensions[0], 
            bckgDimensions[1], 
            fontSize
          );
          ctx.fill();

          // Border based on mastery
          const masteryColor = node.mastery < 30 ? '#ef4444' : node.mastery < 70 ? '#eab308' : '#22c55e';
          ctx.strokeStyle = masteryColor;
          ctx.lineWidth = 1.5 / globalScale;
          ctx.stroke();

          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#1E293B';
          ctx.fillText(label, node.x, node.y);
          
          node.__bckgDimensions = bckgDimensions; // Save dimensions for pointer interaction
        }}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.fillStyle = color;
          const bckgDimensions = node.__bckgDimensions;
          bckgDimensions && ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2, ...bckgDimensions);
        }}
      />
    </div>
  );
}

// ── Styles (defined outside render to avoid recreation) ──────────────────
const containerStyle = {
  width: '100%',
  minHeight: '400px',
  height: '65vh',
  background: 'rgba(255, 255, 255, 0.65)',
  backdropFilter: 'blur(20px)',
  WebkitBackdropFilter: 'blur(20px)',
  borderRadius: '1.5rem',
  overflow: 'hidden',
  border: '1px solid rgba(255, 255, 255, 0.6)',
  boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.05)',
};

const centeredStyle = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
};

const spinnerStyle = {
  width: '40px',
  height: '40px',
  border: '3px solid #E2E8F0',
  borderTop: '3px solid #4F46E5',
  borderRadius: '50%',
  animation: 'spin 1s linear infinite',
};
