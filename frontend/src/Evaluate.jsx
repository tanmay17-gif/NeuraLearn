import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { supabase } from './supabaseClient';
import ReactMarkdown from 'react-markdown';
import { Loader2, ArrowRight } from 'lucide-react';

const _apiRoot = import.meta.env.VITE_API_URL;
const API_BASE = _apiRoot ? `${_apiRoot.replace(/\/api$/, '')}/api` : '/api';

const STUDY_VIDEOS = [
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ", 
  "https://www.youtube.com/watch?v=tVGnOEVg-tI",
  "https://www.youtube.com/watch?v=O5nskjZ_GoI",
  "https://www.youtube.com/watch?v=2GgRUdiYvOs",
  "https://www.youtube.com/watch?v=V74l_zS1x8E"
];

const QUESTIONS = [
  { id: "q1", text: "The summary covered the information I would want from this video." },
  { id: "q2", text: "The summary would be useful to me in practice." },
  { id: "q3", text: "The length of the summary was appropriate for my needs." },
  { id: "q4", text: "The summary was clearly written and easy to follow." },
  { id: "q5", text: "The way the summary was presented suited how I like to read." },
  { id: "q6", text: "Overall, I am satisfied with this summary." },
];

axios.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

const Evaluate = () => {
  const [participantId, setParticipantId] = useState('');
  const [sessionStarted, setSessionStarted] = useState(false);
  const [videoIndex, setVideoIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  
  const [summaryA, setSummaryA] = useState(null);
  const [summaryB, setSummaryB] = useState(null);
  const [shownAsA, setShownAsA] = useState(null); // 'personalized' or 'generic'
  const [profileVersion, setProfileVersion] = useState(null);

  const [ratingsA, setRatingsA] = useState({});
  const [ratingsB, setRatingsB] = useState({});
  const [preference, setPreference] = useState(null);
  const [preferenceReason, setPreferenceReason] = useState('');
  const [completed, setCompleted] = useState(false);

  const startSession = async () => {
    if (!participantId.trim()) return;
    setSessionStarted(true);
    loadVideo(0);
  };

  const loadVideo = async (index) => {
    setLoading(true);
    setRatingsA({});
    setRatingsB({});
    setPreference(null);
    setPreferenceReason('');
    
    try {
      const url = STUDY_VIDEOS[index];
      
      const [personalizedRes, genericRes] = await Promise.all([
        axios.post(`${API_BASE}/process`, { url, use_profile: true }),
        axios.post(`${API_BASE}/process`, { url, use_profile: false })
      ]);

      const isPersonalizedA = Math.random() < 0.5;
      
      if (isPersonalizedA) {
        setSummaryA(personalizedRes.data.summary.join('\n\n'));
        setSummaryB(genericRes.data.summary.join('\n\n'));
        setShownAsA('personalized');
      } else {
        setSummaryA(genericRes.data.summary.join('\n\n'));
        setSummaryB(personalizedRes.data.summary.join('\n\n'));
        setShownAsA('generic');
      }
      
      // Since evaluating users also have normal auth sessions logged in, we fetch their current profile explicitly if needed
      // Actually /process saves log natively on the backend, we don't strictly need to fetch profileversion here. But it's fine.
      
    } catch (error) {
      console.error("Failed to load video summaries", error);
      alert("Failed to load video summaries. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (Object.keys(ratingsA).length < QUESTIONS.length || Object.keys(ratingsB).length < QUESTIONS.length || !preference) {
      alert("Please complete all ratings and select a preference.");
      return;
    }

    try {
      await axios.post(`${API_BASE}/evaluate/submit`, {
        participant_id: participantId,
        video_id: STUDY_VIDEOS[videoIndex],
        shown_as_A: shownAsA,
        ratings_A: ratingsA,
        ratings_B: ratingsB,
        preference,
        preference_reason: preferenceReason,
        profile_version_used: profileVersion
      });

      if (videoIndex + 1 < STUDY_VIDEOS.length) {
        setVideoIndex(prev => prev + 1);
        loadVideo(videoIndex + 1);
      } else {
        setCompleted(true);
      }
    } catch (error) {
      console.error("Failed to submit evaluation", error);
      alert("Failed to submit evaluation. Please try again.");
    }
  };

  const renderRatingScale = (ratings, setRatings) => (
    <div style={{ marginTop: '20px' }}>
      {QUESTIONS.map(q => (
        <div key={q.id} style={{ marginBottom: '15px' }}>
          <div style={{ fontSize: '14px', marginBottom: '8px', color: '#e2e8f0' }}>{q.text}</div>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'space-between' }}>
            {[1, 2, 3, 4, 5].map(val => (
              <label key={val} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer', fontSize: '12px', color: '#94a3b8' }}>
                <input 
                  type="radio" 
                  name={q.id} 
                  value={val} 
                  checked={ratings[q.id] === val}
                  onChange={() => setRatings(prev => ({ ...prev, [q.id]: val }))}
                  style={{ marginBottom: '4px' }}
                />
                {val}
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#64748b', marginTop: '4px' }}>
            <span>Strongly Disagree</span>
            <span>Strongly Agree</span>
          </div>
        </div>
      ))}
    </div>
  );

  if (completed) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a', color: '#f8fafc', padding: '20px' }}>
        <div style={{ background: '#1e293b', padding: '40px', borderRadius: '12px', textAlign: 'center', maxWidth: '500px' }}>
          <h2>Session Complete</h2>
          <p>Thank you for participating in this evaluation study. Your responses have been recorded.</p>
        </div>
      </div>
    );
  }

  if (!sessionStarted) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a', color: '#f8fafc', padding: '20px' }}>
        <div style={{ background: '#1e293b', padding: '40px', borderRadius: '12px', width: '100%', maxWidth: '400px' }}>
          <h2 style={{ marginBottom: '20px' }}>Evaluation Study</h2>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', color: '#94a3b8' }}>Participant ID</label>
            <input 
              type="text" 
              value={participantId}
              onChange={(e) => setParticipantId(e.target.value)}
              placeholder="e.g. P001"
              style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid #334155', background: '#0f172a', color: '#f8fafc' }}
            />
          </div>
          <button 
            onClick={startSession}
            style={{ width: '100%', padding: '12px', borderRadius: '8px', background: '#3b82f6', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}
          >
            Start Session
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0f172a', color: '#f8fafc', padding: '40px 20px', fontFamily: 'Inter, sans-serif' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '30px' }}>
          <h1 style={{ fontSize: '24px' }}>Video {videoIndex + 1} of {STUDY_VIDEOS.length}</h1>
          <div style={{ color: '#94a3b8', fontSize: '14px' }}>Participant: {participantId}</div>
        </div>

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '100px 0', color: '#3b82f6' }}>
            <Loader2 className="animate-spin" size={48} style={{ marginBottom: '20px' }} />
            <p style={{ color: '#94a3b8' }}>Generating comparison summaries...</p>
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '40px' }}>
              {/* Summary A */}
              <div style={{ background: '#1e293b', borderRadius: '12px', padding: '24px' }}>
                <h2 style={{ fontSize: '18px', marginBottom: '20px', borderBottom: '1px solid #334155', paddingBottom: '10px' }}>Summary A</h2>
                <div className="prose prose-invert max-w-none" style={{ maxHeight: '400px', overflowY: 'auto', marginBottom: '30px', fontSize: '14px', lineHeight: '1.6' }}>
                  <ReactMarkdown>{summaryA || ""}</ReactMarkdown>
                </div>
                <div style={{ borderTop: '1px solid #334155', paddingTop: '20px' }}>
                  <h3 style={{ fontSize: '16px', marginBottom: '15px' }}>Rate Summary A</h3>
                  {renderRatingScale(ratingsA, setRatingsA)}
                </div>
              </div>

              {/* Summary B */}
              <div style={{ background: '#1e293b', borderRadius: '12px', padding: '24px' }}>
                <h2 style={{ fontSize: '18px', marginBottom: '20px', borderBottom: '1px solid #334155', paddingBottom: '10px' }}>Summary B</h2>
                <div className="prose prose-invert max-w-none" style={{ maxHeight: '400px', overflowY: 'auto', marginBottom: '30px', fontSize: '14px', lineHeight: '1.6' }}>
                  <ReactMarkdown>{summaryB || ""}</ReactMarkdown>
                </div>
                <div style={{ borderTop: '1px solid #334155', paddingTop: '20px' }}>
                  <h3 style={{ fontSize: '16px', marginBottom: '15px' }}>Rate Summary B</h3>
                  {renderRatingScale(ratingsB, setRatingsB)}
                </div>
              </div>
            </div>

            {/* Preference Selection */}
            <div style={{ background: '#1e293b', borderRadius: '12px', padding: '24px', marginBottom: '40px' }}>
              <h2 style={{ fontSize: '18px', marginBottom: '20px' }}>Overall Preference</h2>
              <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input type="radio" name="preference" value="A" checked={preference === 'A'} onChange={() => setPreference('A')} />
                  I strongly prefer Summary A
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input type="radio" name="preference" value="B" checked={preference === 'B'} onChange={() => setPreference('B')} />
                  I strongly prefer Summary B
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input type="radio" name="preference" value="none" checked={preference === 'none'} onChange={() => setPreference('none')} />
                  No strong preference
                </label>
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', color: '#94a3b8' }}>Why did you make this choice? (Optional)</label>
                <textarea 
                  value={preferenceReason}
                  onChange={(e) => setPreferenceReason(e.target.value)}
                  style={{ width: '100%', height: '80px', padding: '12px', borderRadius: '8px', border: '1px solid #334155', background: '#0f172a', color: '#f8fafc', resize: 'none' }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button 
                onClick={handleSubmit}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 24px', borderRadius: '8px', background: '#3b82f6', color: 'white', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}
              >
                Submit and Continue <ArrowRight size={18} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default Evaluate;
