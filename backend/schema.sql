-- 1. Concepts (The Nodes)
CREATE TABLE IF NOT EXISTS concepts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users NOT NULL,
    label TEXT NOT NULL,
    description TEXT,
    mastery_score INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, label)
);

-- 2. Concept Relationships (The Edges)
CREATE TABLE IF NOT EXISTS concept_edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users NOT NULL,
    from_concept_id UUID REFERENCES concepts(id) ON DELETE CASCADE,
    to_concept_id UUID REFERENCES concepts(id) ON DELETE CASCADE,
    relationship_type TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(from_concept_id, to_concept_id)
);

-- 3. Video Concept Links (The Timestamps & Vision Grounding)
CREATE TABLE IF NOT EXISTS video_concepts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    concept_id UUID REFERENCES concepts(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,
    timestamp_seconds INTEGER,
    visual_insight TEXT,
    visual_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Row Level Security (RLS) Policies
ALTER TABLE concepts ENABLE ROW LEVEL SECURITY;
ALTER TABLE concept_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_concepts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own concepts" ON concepts;
CREATE POLICY "Users can manage their own concepts"
    ON concepts FOR ALL
    USING (auth.uid()::text = user_id::text);

DROP POLICY IF EXISTS "Users can manage their own concept edges" ON concept_edges;
CREATE POLICY "Users can manage their own concept edges"
    ON concept_edges FOR ALL
    USING (auth.uid()::text = user_id::text);

-- 4. Profiles and Tracking
CREATE TABLE IF NOT EXISTS profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users,
    persona_blueprint TEXT,
    instructions JSONB,
    support_level INTEGER DEFAULT 0,
    preferred_length TEXT DEFAULT 'default',
    preferred_format TEXT DEFAULT 'bullets',
    profile_version INTEGER DEFAULT 1,
    feedback_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS profile_version INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS feedback_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW();

CREATE TABLE IF NOT EXISTS profile_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users NOT NULL,
    profile_snapshot JSONB NOT NULL,
    profile_version INTEGER NOT NULL,
    trigger_event TEXT,
    free_text_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generation_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users NOT NULL,
    video_id TEXT NOT NULL,
    use_profile BOOLEAN NOT NULL DEFAULT TRUE,
    profile_version_used INTEGER,
    prompt_text TEXT NOT NULL,
    summary_output TEXT,
    model_name TEXT,
    latency_ms INTEGER,
    cache_hit BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge (
    video_id TEXT PRIMARY KEY,
    title TEXT,
    content TEXT,
    user_id UUID REFERENCES auth.users NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    profile_version_used INTEGER
);

ALTER TABLE knowledge
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS profile_version_used INTEGER;

ALTER TABLE profile_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own profiles" ON profiles;
CREATE POLICY "Users can manage their own profiles" ON profiles FOR ALL USING (auth.uid()::text = user_id::text);
DROP POLICY IF EXISTS "Users can view their own profile history" ON profile_history;
CREATE POLICY "Users can view their own profile history" ON profile_history FOR ALL USING (auth.uid()::text = user_id::text);
DROP POLICY IF EXISTS "Users can view their own generation log" ON generation_log;
CREATE POLICY "Users can view their own generation log" ON generation_log FOR ALL USING (auth.uid()::text = user_id::text);
DROP POLICY IF EXISTS "Users can manage their own knowledge" ON knowledge;
CREATE POLICY "Users can manage their own knowledge" ON knowledge FOR ALL USING (auth.uid()::text = user_id::text);

-- 5. Evaluation Module Responses
CREATE TABLE IF NOT EXISTS evaluation_response (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    participant_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    shown_as_A TEXT NOT NULL,
    ratings_A JSONB,
    ratings_B JSONB,
    preference TEXT,
    preference_reason TEXT,
    profile_version_used INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE evaluation_response ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Participants can insert evaluation responses" ON evaluation_response;
CREATE POLICY "Participants can insert evaluation responses" ON evaluation_response FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS "No one can read evaluation responses" ON evaluation_response;
CREATE POLICY "No one can read evaluation responses" ON evaluation_response FOR SELECT USING (false);
