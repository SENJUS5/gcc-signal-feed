-- GCC Signal Feed schema for Supabase (Postgres + pgvector)
-- Run this once in the Supabase SQL editor.
--
-- Three tables:
--   gccs      one row per company with an India GCC
--   articles  one row per public news article (the source of truth)
--   signals   structured facts the AI pulls out of an article
--
-- Patterns reused from multimodal-rag-project/sql/01_schema.sql:
--   content_hash dedupe, Voyage voyage-3 vector(1024), generated fts column,
--   HNSW + GIN indexes for hybrid search.

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- 1. gccs: the companies we track
-- ---------------------------------------------------------------------------
create table if not exists gccs (
    id               bigint generated always as identity primary key,
    name             text        not null unique,     -- "Walmart Global Tech India"
    parent_company   text,                            -- "Walmart"
    hq_country       text,                            -- parent's home country
    industry         text,                            -- "Retail", "BFSI", ...
    india_cities     text[]      not null default '{}',
    website          text,
    -- "Is it a real GCC?" Only true when a public source says so.
    is_verified_gcc  boolean     not null default false,
    verified_source  text,                            -- URL proving it is a GCC
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2. articles: raw public news. Every signal must point back to one of these.
-- ---------------------------------------------------------------------------
create table if not exists articles (
    id            bigint generated always as identity primary key,
    gcc_id        bigint      references gccs(id) on delete set null,
    url           text        not null unique,        -- the source link
    title         text,
    publisher     text,                               -- "Economic Times", "Mint", ...
    published_at  date,
    content       text        not null,               -- cleaned article text
    content_hash  text        not null unique,        -- sha256(content): same story, two URLs -> stored once
    embedding     vector(1024),                       -- voyage-3; for the Ask box
    -- Extraction bookkeeping: lets the AI script skip articles already done.
    processed_at  timestamptz,                        -- null = not yet read by the AI
    extract_error text,                               -- last failure message, if any
    created_at    timestamptz not null default now(),

    fts tsvector generated always as (
        to_tsvector('english', coalesce(title, '') || ' ' || content)
    ) stored
);

create index if not exists articles_gcc_idx       on articles (gcc_id);
create index if not exists articles_unprocessed  on articles (id) where processed_at is null;
create index if not exists articles_embedding_idx on articles using hnsw (embedding vector_cosine_ops);
create index if not exists articles_fts_idx       on articles using gin (fts);

-- ---------------------------------------------------------------------------
-- 3. signals: one GCC change, pulled from one article
-- ---------------------------------------------------------------------------
create table if not exists signals (
    id           bigint generated always as identity primary key,
    gcc_id       bigint      not null references gccs(id)     on delete cascade,
    article_id   bigint      not null references articles(id) on delete cascade,  -- source is mandatory
    signal_type  text        not null check (signal_type in (
                     'new_centre', 'expansion', 'hiring_push',
                     'office_lease', 'layoff', 'closure')),
    city         text,                                -- null if the article names no city
    signal_date  date        not null,                -- when the event happened / was announced
    summary      text        not null,                -- one line, written by the AI
    strength     smallint    not null check (strength between 1 and 5),
    -- What the job seeker view shows instead of the score.
    direction    text generated always as (
                     case when signal_type in ('layoff', 'closure')
                          then 'shrinking' else 'growing' end
                 ) stored,
    headcount    int,                                 -- only if the article states a number
    extracted_by text,                                -- model name, e.g. "gemini-2.5-flash"
    created_at   timestamptz not null default now(),

    -- Re-running extraction on the same article won't duplicate a signal.
    unique (article_id, gcc_id, signal_type)
);

create index if not exists signals_date_idx on signals (signal_date desc);
create index if not exists signals_gcc_idx  on signals (gcc_id);
create index if not exists signals_type_idx on signals (signal_type);

-- ---------------------------------------------------------------------------
-- 4. Row Level Security
--    The website uses the anon key and can only READ.
--    Laptop scripts use the service key, which bypasses RLS and can write.
-- ---------------------------------------------------------------------------
alter table gccs     enable row level security;
alter table articles enable row level security;
alter table signals  enable row level security;

drop policy if exists "public read" on gccs;
drop policy if exists "public read" on articles;
drop policy if exists "public read" on signals;

create policy "public read" on gccs     for select using (true);
create policy "public read" on articles for select using (true);
create policy "public read" on signals  for select using (true);
