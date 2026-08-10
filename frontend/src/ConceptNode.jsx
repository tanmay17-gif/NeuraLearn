import React, { useState } from 'react';
import { Handle, Position } from '@xyflow/react';

/**
 * ConceptNode — Custom React Flow node.
 *
 * data props:
 *   label            string
 *   description      string
 *   mastery_score    0–100
 *   timestamp_seconds number
 *   visual_insight   string | null   (from vision LLM)
 *   onClick          (data) => void
 */
export default function ConceptNode({ data }) {
  const [showInsight, setShowInsight] = useState(false);

  // ── Mastery colour ──────────────────────────────────────────────────────
  const masteryColor = getMasteryColor(data.mastery_score);
  const masteryLabel = getMasteryLabel(data.mastery_score);
  const hasInsight = Boolean(data.visual_insight);

  return (
    <div
      onClick={() => data.onClick?.(data)}
      style={{
        padding: '16px 20px',
        borderRadius: '20px',
        background: 'rgba(255, 255, 255, 0.75)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        color: '#0F172A',
        border: `1px solid rgba(255, 255, 255, 0.6)`,
        boxShadow: `0 10px 25px -5px ${masteryColor}20, 0 8px 10px -6px rgba(0, 0, 0, 0.05), inset 0 1px 0 rgba(255,255,255,1)`,
        textAlign: 'center',
        minWidth: '180px',
        maxWidth: '240px',
        cursor: 'pointer',
        fontFamily: '"SF Pro Display", "Inter", sans-serif',
        transition: 'all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1)',
        userSelect: 'none',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '4px', background: masteryColor, opacity: 0.8 }} />
      <Handle type="target" position={Position.Top} style={{ background: '#fff', width: 10, height: 10, border: `2px solid ${masteryColor}`, top: -5 }} />

      {/* Label */}
      <div style={{ fontWeight: 800, fontSize: '15px', marginBottom: '6px', lineHeight: 1.2, letterSpacing: '-0.01em', color: '#1E293B' }}>
        {data.label}
      </div>

      {/* Description */}
      {data.description && (
        <div style={{ fontSize: '10px', color: '#94a3b8', lineHeight: 1.4, marginBottom: '6px' }}>
          {data.description}
        </div>
      )}

      {/* Mastery badge */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: '6px', flexWrap: 'wrap' }}>
        <span style={{
          fontSize: '9px',
          fontWeight: 700,
          padding: '2px 7px',
          borderRadius: '20px',
          background: `${masteryColor}22`,
          color: masteryColor,
          border: `1px solid ${masteryColor}44`,
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
        }}>
          {masteryLabel}
        </span>

        {/* Timestamp badge */}
        {data.timestamp_seconds > 0 && (
          <span style={{
            fontSize: '9px',
            padding: '2px 7px',
            borderRadius: '20px',
            background: '#F8FAFC',
            color: '#64748b',
            border: '1px solid #E2E8F0',
            fontWeight: 600,
          }}>
            ⏱ {formatTime(data.timestamp_seconds)}
          </span>
        )}
      </div>

      {/* Vision insight toggle */}
      {hasInsight && (
        <div style={{ marginTop: '8px' }}>
          <button
            onClick={(e) => { e.stopPropagation(); setShowInsight(!showInsight); }}
            style={{
              fontSize: '9px',
              padding: '4px 10px',
              borderRadius: '8px',
              background: showInsight ? '#4F46E5' : '#F8FAFC',
              color: showInsight ? 'white' : '#4F46E5',
              border: '1px solid #4F46E5',
              cursor: 'pointer',
              fontWeight: 700,
              letterSpacing: '0.03em',
              transition: 'all 0.15s ease',
            }}
          >
            👁 Visual Insight
          </button>

          {showInsight && (
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                marginTop: '8px',
                padding: '10px',
                background: '#F8FAFC',
                borderRadius: '8px',
                fontSize: '10px',
                color: '#475569',
                lineHeight: 1.5,
                textAlign: 'left',
                border: '1px solid #E2E8F0',
                maxHeight: '120px',
                overflowY: 'auto',
                boxShadow: 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
              }}
            >
              {data.visual_insight}
            </div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ background: '#fff', width: 10, height: 10, border: `2px solid ${masteryColor}`, bottom: -5 }} />
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function getMasteryColor(score) {
  if (score == null || score < 30) return '#ef4444'; // red — low
  if (score < 70) return '#eab308';                  // yellow — learning
  return '#22c55e';                                   // green — mastered
}

function getMasteryLabel(score) {
  if (score == null || score < 30) return 'Review';
  if (score < 70) return 'Learning';
  return 'Mastered';
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
