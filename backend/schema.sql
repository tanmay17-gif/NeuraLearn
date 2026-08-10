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

CREATE POLICY "Users can manage their own concepts"
    ON concepts FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage their own concept edges"
    ON concept_edges FOR ALL
    USING (auth.uid() = user_id);
