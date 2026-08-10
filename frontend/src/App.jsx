import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { supabase } from './supabaseClient';
import ReactPlayer from 'react-player';

import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import { 
  TvMinimalPlay as Youtube, 
  Zap, 
  BrainCircuit, 
  CircleCheck as CheckCircle2, 
  ArrowRight, 
  LoaderCircle as Loader2,
  BookOpen,
  History,
  FileText,
  LayoutDashboard,
  GraduationCap,
  Network,
  Search,
  Brain,
  RefreshCw,
  Copy,
  ChevronRight,
  Video,
  Sparkles,
  Upload,
  Link as LinkIcon,
  X
} from 'lucide-react';
import KnowledgeGraph from './KnowledgeGraph';
import GlobalGraphView from './GlobalGraphView';

const _apiRoot = import.meta.env.VITE_API_URL;
const API_BASE = _apiRoot ? `${_apiRoot.replace(/\/api$/, '')}/api` : '/api';

axios.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

const Flashcard = ({ question, answer, concept_id, onFeedback }) => {
  const [flipped, setFlipped] = useState(false);
  const [feedbackGiven, setFeedbackGiven] = useState(null);

  const handleRating = (e, isCorrect) => {
    e.stopPropagation(); // prevent flipping
    setFeedbackGiven(isCorrect ? 'correct' : 'incorrect');
    if (onFeedback && concept_id) {
      onFeedback(concept_id, isCorrect);
    }
  };

  return (
    <div 
      onClick={() => setFlipped(!flipped)}
      style={{ height: '220px', perspective: '1000px', cursor: 'pointer' }}
    >
      <motion.div
        animate={{ rotateY: flipped ? 180 : 0 }}
        transition={{ duration: 0.6, type: 'spring', stiffness: 260, damping: 20 }}
        style={{ width: '100%', height: '100%', position: 'relative', transformStyle: 'preserve-3d' }}
      >
        <div style={{
          position: 'absolute', width: '100%', height: '100%', backfaceVisibility: 'hidden',
          background: 'white', border: '1px solid var(--glass-stroke)', borderRadius: '1.5rem',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem',
          textAlign: 'center', fontWeight: 600, color: 'var(--text-main)', boxShadow: 'var(--shadow-md)'
        }}>
          {question}
        </div>
        <div style={{
          position: 'absolute', width: '100%', height: '100%', backfaceVisibility: 'hidden',
          background: 'linear-gradient(135deg, var(--primary) 0%, #6366F1 100%)',
          borderRadius: '1.5rem', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          padding: '2rem', textAlign: 'center', transform: 'rotateY(180deg)', color: 'white'
        }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', overflowY: 'auto' }}>
            {answer}
          </div>
          {concept_id && (
            <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.2)', paddingTop: '0.75rem', width: '100%', justifyContent: 'center' }}>
              <button 
                onClick={(e) => handleRating(e, true)}
                disabled={feedbackGiven !== null}
                style={{ 
                  background: feedbackGiven === 'correct' ? '#22c55e' : 'rgba(255,255,255,0.15)', border: 'none', padding: '0.4rem 0.8rem', borderRadius: '8px', color: 'white', cursor: feedbackGiven !== null ? 'default' : 'pointer', fontSize: '0.8rem', fontWeight: 600, transition: 'background 0.2s'
                }}
              >
                {feedbackGiven === 'correct' ? '✓ Mastered' : '👍 Knew it'}
              </button>
              <button 
                onClick={(e) => handleRating(e, false)}
                disabled={feedbackGiven !== null}
                style={{ 
                  background: feedbackGiven === 'incorrect' ? '#ef4444' : 'rgba(255,255,255,0.15)', border: 'none', padding: '0.4rem 0.8rem', borderRadius: '8px', color: 'white', cursor: feedbackGiven !== null ? 'default' : 'pointer', fontSize: '0.8rem', fontWeight: 600, transition: 'background 0.2s'
                }}
              >
                {feedbackGiven === 'incorrect' ? 'Needs Review' : '👎 Forgot'}
              </button>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
};

function App() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [moduleLoading, setModuleLoading] = useState(null);
  const [result, setResult] = useState(null);
  const [modules, setModules] = useState({ notes: null, visuals: null, map: null, flashcards: null });
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('digest');
  const [level, setLevel] = useState('intermediate');
  const [feedback, setFeedback] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [userId, setUserId] = useState('');
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userProfile, setUserProfile] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [personaBlueprint, setPersonaBlueprint] = useState('');
  const [dynamicExtra, setDynamicExtra] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [authEmail, setAuthEmail] = useState('');
  const [authSent, setAuthSent] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [sourceType, setSourceType] = useState('youtube');
  const [uploadFile, setUploadFile] = useState(null);
  const [showGlobalGraph, setShowGlobalGraph] = useState(false);
  const [mapMergeStats, setMapMergeStats] = useState(null);
  
  // Video Player Ref & State for seeking and mini-player
  const playerRef = useRef(null);
  const [showMiniPlayer, setShowMiniPlayer] = useState(false);

  useEffect(() => {
    // Check if user is already logged in
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user) {
        const id = session.user.id;
        setUserId(id);
        setIsLoggedIn(true);
        fetchProfile(id);
      }
    });

    // Listen for auth changes (login / logout)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.user) {
        const id = session.user.id;
        setUserId(id);
        setIsLoggedIn(true);
        fetchProfile(id);
      } else {
        setUserId('');
        setIsLoggedIn(false);
        setUserProfile(null);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const fetchProfile = async (id) => {
    try {
      const response = await axios.get(`${API_BASE}/profile/${id}`);
      setUserProfile(response.data);
      setPersonaBlueprint(response.data.persona_blueprint || '');
    } catch (err) { console.error("Fetch profile error", err); }
  };

  const handleLogin = async () => {
    if (!authEmail.trim()) return;
    setAuthLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email: authEmail.trim(),
      options: { emailRedirectTo: window.location.origin }
    });
    setAuthLoading(false);
    if (!error) setAuthSent(true);
    else alert('Error sending link: ' + error.message);
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
    setResult(null);
    setAuthSent(false);
    setAuthEmail('');
    setModules({ notes: null, visuals: null, map: null, flashcards: null });
  };

  const saveCustomInstructions = async () => {
    try {
      await axios.post(`${API_BASE}/profile/custom`, { 
        user_id: userId, 
        blueprint: personaBlueprint
      });
      setShowSettings(false);
      fetchProfile(userId);
      alert('✅ Persona saved successfully!');
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Unknown error';
      console.error("Save persona blueprint error:", msg, err);
      alert(`❌ Failed to save persona: ${msg}`);
    }
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery) return;
    try {
      const response = await axios.post(`${API_BASE}/search`, { 
        query: searchQuery,
        user_id: userId 
      });
      setSearchResults(response.data.results);
    } catch (err) { console.error("Search error", err); }
  };

  const handleFeedback = async (moduleType, rating) => {
    setFeedback(prev => ({ ...prev, [moduleType]: rating }));
    try {
      await axios.post(`${API_BASE}/feedback`, {
        video_id: result.video_id,
        module: moduleType,
        rating: rating,
        level: level,
        user_id: userId
      });
      // Refresh profile to show updated automated instructions if any
      fetchProfile(userId);
    } catch (err) { console.error("Feedback error", err); }
  };

  const handleProcess = async (e) => {
    e.preventDefault();
    if (sourceType === 'youtube' && !url) return;
    if (sourceType === 'upload' && !uploadFile) return;

    setLoading(true); setError(null); setResult(null);
    setModules({ notes: null, visuals: null, map: null, flashcards: null });
    setFeedback({});

    try {
      let data;
      if (sourceType === 'youtube') {
        const response = await axios.post(`${API_BASE}/process`, { 
          url, level, user_id: userId, dynamic_extra: dynamicExtra
        });
        data = response.data;
      } else {
        const formData = new FormData();
        formData.append('file', uploadFile);
        formData.append('level', level);
        formData.append('user_id', userId || 'default_user');
        formData.append('dynamic_extra', dynamicExtra);
        
        const response = await axios.post(`${API_BASE}/upload`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        data = response.data;
      }
      setResult(data);
      setActiveTab('digest');
    } catch (err) { 
      setError(err.response?.data?.detail || 'An unexpected error occurred.');
    } finally { 
      setLoading(false); 
    }
  };

  const generateModule = async (moduleType) => {
    if (!result) return;
    setModuleLoading(moduleType);
    try {
      const response = await axios.post(`${API_BASE}/generate/${moduleType}`, {
        video_id: result.video_id, 
        transcript: result.transcript, 
        video_url: url,
        level: level,
        user_id: userId
      });
      const data = response.data.data;
      setModules(prev => ({ ...prev, [moduleType]: data }));
      // Surface merge stats when the concept map is generated
      if (moduleType === 'map' && data?.merge_stats) {
        setMapMergeStats(data.merge_stats);
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Unknown error';
      console.error(`Generation error for [${moduleType}]:`, msg, err);
      alert(`❌ Generation failed: ${msg}`);
    }
    finally { setModuleLoading(null); }
  };

  const handleConceptFeedback = async (conceptId, correct) => {
    try {
      await axios.post(`${API_BASE}/graph/feedback`, { concept_id: conceptId, correct });
    } catch (err) { console.error('Concept feedback error', err); }
  };

  const [copied, setCopied] = useState(null);
  const handleCopy = (text, type) => {
    let content = text;
    if (type === 'digest' && Array.isArray(text)) content = text.join('\n');
    navigator.clipboard.writeText(content);
    setCopied(type);
    setTimeout(() => setCopied(null), 2000);
  };

  const ModulePlaceholder = ({ type, title, icon: Icon }) => (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
      style={{ textAlign: 'center', padding: '5rem 2rem', background: 'rgba(255,255,255,0.4)', borderRadius: '2rem', border: '2px dashed var(--text-dim)', opacity: 0.8 }}
    >
      <div style={{ width: '80px', height: '80px', background: 'white', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1.5rem', boxShadow: 'var(--shadow-md)' }}>
        <Icon size={32} color="var(--primary)" />
      </div>
      <h3 style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>Ready for Synthesis?</h3>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2.5rem', maxWidth: '400px', margin: '0 auto 2.5rem' }}>
        Unlock {title} using our specialized AI engine. Optimized for research-grade accuracy.
      </p>
      <button onClick={() => generateModule(type)} disabled={moduleLoading === type} className="btn-primary" style={{ margin: '0 auto' }}>
        {moduleLoading === type ? <RefreshCw className="animate-spin" /> : <Sparkles size={18} />}
        {moduleLoading === type ? 'Synthesizing...' : `Generate ${title}`}
      </button>
    </motion.div>
  );

  const FeedbackControls = ({ moduleType }) => (
    <div style={{ display: 'flex', gap: '0.75rem', marginTop: '2.5rem', alignItems: 'center', paddingTop: '1.5rem', borderTop: '1px solid #F1F5F9' }}>
      <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Insight helpful?</span>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button 
          onClick={() => handleFeedback(moduleType, 'up')}
          style={{ 
            padding: '0.6rem 1rem', borderRadius: '0.75rem', border: '1px solid #E2E8F0', background: feedback[moduleType] === 'up' ? 'var(--primary)' : 'white', 
            color: feedback[moduleType] === 'up' ? 'white' : 'var(--text-dim)', cursor: 'pointer', transition: 'all 0.2s ease', display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600
          }}
        >
          <span>👍</span> {feedback[moduleType] === 'up' ? 'Helpful' : ''}
        </button>
        <button 
          onClick={() => handleFeedback(moduleType, 'down')}
          style={{ 
            padding: '0.6rem 1rem', borderRadius: '0.75rem', border: '1px solid #E2E8F0', background: feedback[moduleType] === 'down' ? 'var(--accent)' : 'white', 
            color: feedback[moduleType] === 'down' ? 'white' : 'var(--text-dim)', cursor: 'pointer', transition: 'all 0.2s ease', display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600
          }}
        >
          <span>👎</span> {feedback[moduleType] === 'down' ? 'Not for me' : ''}
        </button>
      </div>
    </div>
  );

  return (
    <div style={{ minHeight: '100vh', position: 'relative' }}>
      {/* Visual Depth Background */}
      <div className="bg-canvas">
        <motion.div 
          animate={{ x: [0, 50, 0], y: [0, 30, 0] }} 
          transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
          className="bg-orb orb-1" 
        />
        <motion.div 
          animate={{ x: [0, -40, 0], y: [0, 50, 0] }} 
          transition={{ duration: 25, repeat: Infinity, ease: "easeInOut", delay: 2 }}
          className="bg-orb orb-2" 
        />
        <motion.div 
          animate={{ scale: [1, 1.1, 1] }} 
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          className="bg-orb orb-3" 
        />
      </div>
      <div className="neural-grid"></div>

      <div className="main-container" style={{ maxWidth: '1100px' }}>
        {/* Settings Modal */}
        <AnimatePresence>
          {showSettings && (
            <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(16px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem' }}>
              <motion.div 
                initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
                className="glass-card" style={{ maxWidth: '600px', width: '100%', padding: '3rem' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                  <h2 style={{ margin: 0, fontWeight: 900, fontSize: '1.8rem' }}>Persona Configuration</h2>
                  <button onClick={() => setShowSettings(false)} style={{ background: 'var(--primary-light)', border: 'none', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--primary)' }}>&times;</button>
                </div>
                
                <div style={{ marginBottom: '2.5rem' }}>
                  <span className="label-premium">Identity Blueprint</span>
                  <p className="description-premium">Define your academic persona. This instructions the AI on the tone, depth, and style of every synthesis.</p>
                  <textarea 
                    className="input-field" style={{ minHeight: '200px', padding: '1.5rem', fontSize: '1rem' }}
                    value={personaBlueprint} onChange={(e) => setPersonaBlueprint(e.target.value)}
                    placeholder="E.g., I am a medical student. Focus on clinical applications and terminology..."
                  />
                </div>

                <button onClick={saveCustomInstructions} className="btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '1.25rem' }}>Update Identity</button>
              </motion.div>
            </div>
          )}
        </AnimatePresence>

        {/* Cinematic Header */}
        <header style={{ 
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
          marginBottom: '4rem', padding: '1.5rem 0'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{ width: '48px', height: '48px', background: 'var(--primary)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', boxShadow: '0 10px 25px rgba(79, 70, 229, 0.3)' }}>
              <Brain size={28} />
            </div>
            <h1 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 900, letterSpacing: '-0.05em' }}>NeuraLearn</h1>
          </div>

          {isLoggedIn && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <button
                onClick={() => setShowGlobalGraph(true)}
                style={{ padding: '0.75rem 1.25rem', borderRadius: '14px', background: '#0f172a', border: '1px solid #334155', color: '#94a3b8', fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}
              >
                <Network size={18} /> My Knowledge Graph
              </button>
              <button onClick={() => setShowSettings(true)} className="btn-primary" style={{ padding: '0.75rem 1.25rem', borderRadius: '14px', gap: '0.75rem' }}>
                <GraduationCap size={20} />
                <span style={{ fontWeight: 800 }}>Persona Settings</span>
              </button>
              <button onClick={handleLogout} style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem' }}>Exit</button>
            </div>
          )}
        </header>

        <main>
          {/* Global Knowledge Graph full-page view */}
          {showGlobalGraph && (
            <GlobalGraphView onBack={() => setShowGlobalGraph(false)} />
          )}

          {!showGlobalGraph && !isLoggedIn ? (
            <motion.div 
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              style={{ maxWidth: '500px', margin: '10vh auto', textAlign: 'center' }}
            >
              <div className="glass-card" style={{ padding: '4rem' }}>
                <div style={{ width: '70px', height: '70px', background: 'var(--primary)', borderRadius: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', margin: '0 auto 2rem', boxShadow: '0 15px 35px rgba(79, 70, 229, 0.4)' }}>
                  <Brain size={40} />
                </div>
                <h2 style={{ fontSize: '2.5rem', fontWeight: 900, marginBottom: '1rem', letterSpacing: '-0.05em' }}>Welcome Back</h2>
                <p style={{ color: 'var(--text-dim)', marginBottom: '3rem', fontSize: '1.1rem', lineHeight: '1.6' }}>
                  Access your personalized Knowledge OS and identity-driven study guides.
                </p>

                {authSent ? (
                  <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
                    <div style={{ padding: '2rem', background: 'var(--primary-light)', borderRadius: '1.5rem', border: '1px solid rgba(79, 70, 229, 0.1)', color: 'var(--primary)', fontWeight: 700 }}>
                      <CheckCircle2 size={32} style={{ marginBottom: '1rem' }} />
                      <p>Magic Link Sent!</p>
                      <p style={{ fontSize: '0.85rem', fontWeight: 500, marginTop: '0.5rem', opacity: 0.8 }}>Check your email to enter the hub.</p>
                    </div>
                  </motion.div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                    <input 
                      type="email" placeholder="Enter academic email..." className="input-field"
                      value={authEmail} onChange={(e) => setAuthEmail(e.target.value)}
                      style={{ height: '60px', textAlign: 'center', fontSize: '1.1rem' }}
                    />
                    <button onClick={handleLogin} disabled={authLoading} className="btn-primary" style={{ height: '60px', justifyContent: 'center', fontSize: '1.1rem' }}>
                      {authLoading ? <Loader2 className="animate-spin" size={24} /> : 'Request Magic Link'}
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          ) : !showGlobalGraph && (
            <>
              {/* Centralized Hub */}
              <div className="glass-card" style={{ marginBottom: '4rem', padding: '4rem' }}>
                <div style={{ textAlign: 'center', marginBottom: '3.5rem' }}>
                  <h2 style={{ fontSize: '3rem', marginBottom: '1rem', fontWeight: 900, letterSpacing: '-0.06em', color: 'var(--text-main)' }}>Smart Study Hub</h2>
                  <p className="description-premium" style={{ fontSize: '1.2rem', maxWidth: '600px', margin: '0 auto' }}>Transform complex video sources into personalized, high-fidelity study guides.</p>
                </div>
                {/* Source Toggle */}
                <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', marginBottom: '3rem', background: '#F8FAFC', padding: '0.4rem', borderRadius: '1rem', width: 'fit-content', margin: '0 auto 3rem auto', flexWrap: 'wrap' }}>
                  <button 
                    type="button"
                    onClick={() => setSourceType('youtube')}
                    style={{ 
                      padding: '0.8rem 2rem', borderRadius: '0.75rem', border: 'none', cursor: 'pointer',
                      background: sourceType === 'youtube' ? 'white' : 'transparent',
                      color: sourceType === 'youtube' ? 'var(--primary)' : 'var(--text-dim)',
                      fontWeight: 700, transition: 'all 0.3s ease',
                      boxShadow: sourceType === 'youtube' ? '0 4px 12px rgba(0,0,0,0.05)' : 'none'
                    }}
                  >
                    YouTube Link
                  </button>
                  <button 
                    type="button"
                    onClick={() => setSourceType('upload')}
                    style={{ 
                      padding: '0.8rem 2rem', borderRadius: '0.75rem', border: 'none', cursor: 'pointer',
                      background: sourceType === 'upload' ? 'white' : 'transparent',
                      color: sourceType === 'upload' ? 'var(--primary)' : 'var(--text-dim)',
                      fontWeight: 700, transition: 'all 0.3s ease',
                      boxShadow: sourceType === 'upload' ? '0 4px 12px rgba(0,0,0,0.05)' : 'none'
                    }}
                  >
                    Local Upload
                  </button>
                </div>
                
                <form onSubmit={handleProcess} style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                  <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
                    <div style={{ flex: '3', minWidth: '240px', position: 'relative' }}>
                      {sourceType === 'youtube' ? (
                        <>
                          <Youtube size={22} style={{ position: 'absolute', left: '1.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--primary)' }} />
                          <input 
                            type="text" className="input-field" placeholder="Paste YouTube Link..." 
                            style={{ paddingLeft: '4.5rem', height: '65px', fontSize: '1.1rem' }}
                            value={url} onChange={(e) => setUrl(e.target.value)} 
                          />
                        </>
                      ) : (
                        <>
                          <Upload size={22} style={{ position: 'absolute', left: '1.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--primary)' }} />
                          <input 
                            type="file" accept="video/*" className="input-field"
                            style={{ paddingLeft: '4.5rem', height: '65px', fontSize: '0.95rem', display: 'flex', alignItems: 'center', paddingTop: '1.1rem' }}
                            onChange={(e) => setUploadFile(e.target.files[0])}
                          />
                        </>
                      )}
                    </div>
                    <select 
                      value={level} onChange={(e) => setLevel(e.target.value)}
                      className="input-field"
                      style={{ flex: '1', minWidth: '220px', height: '65px', fontSize: '1rem' }}
                    >
                      <option value="beginner">Foundational Summary</option>
                      <option value="intermediate">Advanced Synthesis</option>
                      <option value="expert">Expert Briefing</option>
                    </select>
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                      <Video size={18} color="var(--primary)" />
                      <span className="label-premium" style={{ marginBottom: 0 }}>Specific Focus Areas</span>
                    </div>
                    <textarea 
                      value={dynamicExtra} onChange={(e) => setDynamicExtra(e.target.value)}
                      placeholder="E.g., Highlight the historical context or explain the mathematical proofs..."
                      className="input-field"
                      style={{ minHeight: '120px', resize: 'vertical', padding: '1.5rem', fontSize: '1rem' }}
                    />
                  </div>

                  <button type="submit" className="btn-primary" disabled={loading} style={{ width: '100%', justifyContent: 'center', padding: '1.5rem', fontSize: '1.2rem', borderRadius: '1.5rem' }}>
                    {loading ? <Loader2 className="animate-spin" size={24} /> : <Zap size={24} />}
                    {loading ? 'Synthesizing Knowledge...' : 'Generate Personalized Guide'}
                  </button>
                </form>
              </div>

              {/* Persona Insights Area */}
              <AnimatePresence>
                {userProfile && userProfile.instructions?.length > 0 && (
                  <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0 }} style={{ marginBottom: '3rem' }}>
                    <div className="glass-card" style={{ borderLeft: '4px solid var(--primary)', padding: '1.5rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h3 style={{ fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                          <BrainCircuit size={18} color="var(--primary)" /> 
                          Learned Behaviors for <span style={{ color: 'var(--primary)' }}>{userId}</span>
                        </h3>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                        {userProfile.instructions.map((ins, i) => (
                          <div key={i} style={{ padding: '0.4rem 0.8rem', background: 'white', borderRadius: '0.75rem', fontSize: '0.8rem', border: '1px solid #E2E8F0', color: 'var(--text-dim)' }}>
                            ✨ {ins}
                          </div>
                        ))}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Results Area */}
              <AnimatePresence mode="wait">
                {result && (
                  <motion.div key="result" initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}>
                    {/* Modern Capsule Tab Bar */}
                    <div style={{ 
                      display: 'flex', gap: '0.5rem', marginBottom: '2rem', padding: '0.5rem', 
                      background: 'var(--glass)', borderRadius: '1.5rem', overflowX: 'auto', 
                      scrollbarWidth: 'none', border: '1px solid var(--glass-stroke)'
                    }}>
                      {[
                        { id: 'digest', label: 'Quick Digest', icon: LayoutDashboard },
                        { id: 'notes', label: 'Study Notes', icon: FileText },
                        { id: 'visual', label: 'Visual Insights', icon: Youtube },
                        { id: 'flashcards', label: 'Active Recall', icon: GraduationCap },
                        { id: 'map', label: 'Concept Map', icon: Network }
                      ].map(tab => (
                        <button 
                          key={tab.id} onClick={() => setActiveTab(tab.id)}
                          style={{ 
                            padding: '0.8rem 1.25rem', borderRadius: '1rem', border: 'none',
                            background: activeTab === tab.id ? 'var(--primary)' : 'transparent',
                            color: activeTab === tab.id ? 'white' : 'var(--text-dim)',
                            fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.6rem', 
                            cursor: 'pointer', transition: 'all 0.3s ease', whiteSpace: 'nowrap'
                          }}
                        >
                          <tab.icon size={18} /> {tab.label}
                        </button>
                      ))}
                    </div>

                    <div className="glass-card" style={{ minHeight: '500px', boxShadow: 'var(--shadow-lg)' }}>
                      {activeTab === 'digest' && (
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '2.5rem', flexWrap: 'wrap', gap: '1rem' }}>
                            <h2 style={{ fontSize: 'clamp(1.4rem, 4vw, 2rem)', maxWidth: '80%' }}>{result.title}</h2>
                            <button onClick={() => handleCopy(result.summary, 'digest')} style={{ padding: '0.75rem', borderRadius: '1rem', background: 'var(--primary-light)', border: 'none', color: 'var(--primary)', cursor: 'pointer' }}>
                              {copied === 'digest' ? <CheckCircle2 size={20} /> : <Copy size={20} />}
                            </button>
                          </div>

                          {/* ONLY show persona card if custom_insights exist */}
                          {result.custom_insights ? (
                            <motion.div 
                              initial={{ opacity: 0, y: 20 }} 
                              animate={{ opacity: 1, y: 0 }}
                              style={{ 
                                padding: '2.5rem', 
                                background: 'linear-gradient(135deg, rgba(79, 70, 229, 0.05) 0%, rgba(6, 182, 212, 0.05) 100%)', 
                                borderRadius: '2rem', border: '1px solid rgba(79, 70, 229, 0.15)',
                                position: 'relative', overflow: 'hidden'
                              }}
                            >
                              <div style={{ position: 'absolute', top: '-40px', right: '-40px', width: '200px', height: '200px', background: 'var(--primary)', opacity: 0.04, borderRadius: '50%' }}></div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
                                <div style={{ padding: '0.8rem', background: 'var(--primary)', color: 'white', borderRadius: '14px', boxShadow: '0 10px 20px rgba(79, 70, 229, 0.2)' }}>
                                  <Brain size={24} />
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                  <span style={{ fontSize: '0.75rem', fontWeight: 900, color: 'var(--primary)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Persona Synthesis</span>
                                  <h3 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 900, letterSpacing: '-0.03em' }}>Tailored For You</h3>
                                </div>
                              </div>
                              <div className="markdown-body" style={{ fontSize: '1.1rem', color: 'var(--text-main)', lineHeight: '1.8' }}>
                                <ReactMarkdown>{result.custom_insights}</ReactMarkdown>
                              </div>
                            </motion.div>
                          ) : (
                            // Fallback: plain summary bullets if no persona insights
                            <div style={{ display: 'grid', gap: '1.5rem' }}>
                              {result.summary.map((b, i) => (
                                <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }} key={i} style={{ display: 'flex', gap: '1.5rem', padding: '1.5rem', background: 'white', borderRadius: '1.5rem', border: '1px solid #E2E8F0' }}>
                                  <div style={{ width: '36px', height: '36px', borderRadius: '10px', background: 'var(--primary-light)', color: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: '0.85rem', flexShrink: 0 }}>{i + 1}</div>
                                  <div className="markdown-body" style={{ fontSize: '1rem', lineHeight: '1.7', color: 'var(--text-main)', flex: 1 }}><ReactMarkdown>{b}</ReactMarkdown></div>
                                </motion.div>
                              ))}
                            </div>
                          )}
                          <FeedbackControls moduleType="digest" />
                        </motion.div>
                      )}

                      {activeTab === 'notes' && (
                        modules.notes ? (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="markdown-body">
                            <ReactMarkdown>{modules.notes}</ReactMarkdown>
                            <FeedbackControls moduleType="notes" />
                          </motion.div>
                        ) : <ModulePlaceholder type="notes" title="Study Notes" icon={FileText} />
                      )}

                      {activeTab === 'visual' && (
                        modules.visuals ? (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="markdown-body">
                            <ReactMarkdown>{modules.visuals}</ReactMarkdown>
                            <FeedbackControls moduleType="visuals" />
                          </motion.div>
                        ) : <ModulePlaceholder type="visuals" title="Visual Insights" icon={Youtube} />
                      )}

                      {activeTab === 'flashcards' && (
                        modules.flashcards ? (
                          <div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1.5rem' }}>
                              {modules.flashcards.map((c, i) => (
                                <Flashcard 
                                  key={i} 
                                  {...c} 
                                  onFeedback={handleConceptFeedback} 
                                />
                              ))}
                            </div>
                            <FeedbackControls moduleType="flashcards" />
                          </div>
                        ) : <ModulePlaceholder type="flashcards" title="Memory Cards" icon={GraduationCap} />
                      )}

                      {activeTab === 'map' && (
                        modules.map ? (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                            <div style={{ height: '600px', background: 'rgba(255,255,255,0.7)', borderRadius: '1.5rem', overflow: 'hidden', border: '1px solid #E2E8F0', position: 'relative', boxShadow: 'var(--shadow-md)' }}>
                              {mapMergeStats && (
                                <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, display: 'flex', gap: '8px' }}>
                                  <div style={{ background: '#0f172a', color: '#fff', padding: '6px 12px', borderRadius: '10px', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Network size={14} color="#818cf8" /> {mapMergeStats.merged} concepts merged into your graph
                                  </div>
                                  <div style={{ background: '#0f172a', color: '#fff', padding: '6px 12px', borderRadius: '10px', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Sparkles size={14} color="#f59e0b" /> {mapMergeStats.new} new concepts added
                                  </div>
                                  <div style={{ background: '#0f172a', color: '#fff', padding: '6px 12px', borderRadius: '10px', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <LinkIcon size={14} color="#94a3b8" /> {mapMergeStats.edges_added} connections mapped
                                  </div>
                                </div>
                              )}
                              <KnowledgeGraph 
                                graphData={modules.map} 
                                onNodeClick={(timestamp) => {
                                  if (timestamp >= 0) {
                                    setShowMiniPlayer(true);
                                    if (playerRef.current) {
                                      playerRef.current.seekTo(timestamp, 'seconds');
                                    }
                                  }
                                }}
                              />
                            </div>
                            <div style={{ marginTop: '1rem', textAlign: 'right' }}>
                              <button
                                onClick={() => setShowGlobalGraph(true)}
                                style={{ fontSize: '0.8rem', padding: '0.5rem 1rem', background: '#0f172a', border: '1px solid #334155', color: '#6366f1', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
                              >
                                View Full Knowledge Graph →
                              </button>
                            </div>
                            <FeedbackControls moduleType="map" />
                          </motion.div>
                        ) : <ModulePlaceholder type="map" title="Concept Map" icon={Network} />
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          )}
        </main>

        {/* Floating Mini Player (Picture-in-Picture style) */}
        <AnimatePresence>
          {showMiniPlayer && sourceType === 'youtube' && url && (
            <motion.div
              initial={{ opacity: 0, y: 50, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 50, scale: 0.9 }}
              style={{
                position: 'fixed',
                bottom: '2rem',
                right: '2rem',
                width: '320px',
                background: '#0F172A',
                borderRadius: '16px',
                boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255,255,255,0.1)',
                zIndex: 9999,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column'
              }}
            >
              {/* Header bar to close */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'rgba(0,0,0,0.4)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94a3b8', fontSize: '0.75rem', fontWeight: 600 }}>
                  <Video size={14} /> Playing Reference
                </div>
                <button 
                  onClick={() => setShowMiniPlayer(false)}
                  style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px', display: 'flex' }}
                >
                  <X size={16} />
                </button>
              </div>
              
              {/* Player */}
              <div style={{ position: 'relative', paddingTop: '56.25%' }}>
                <ReactPlayer
                  ref={playerRef}
                  url={url}
                  controls
                  playing
                  width="100%"
                  height="100%"
                  style={{ position: 'absolute', top: 0, left: 0 }}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default App;
