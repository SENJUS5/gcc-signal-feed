-- 03_search_fns.sql: search over news articles for the Ask box.
-- Adapted from multimodal-rag-project/sql/02_search_fns.sql (same three-layer design:
-- semantic, keyword, hybrid with Reciprocal Rank Fusion). Run once in the Supabase SQL editor.
--
-- Changes from the RAG version:
--   * searches `articles` (embedding + fts) instead of `rag_chunks`; no source_type filter.
--   * keyword search uses OR between words instead of AND. Questions are natural
--     language ("Which companies are hiring in Hyderabad?"); with AND, an article must
--     contain every word and usually nothing matches. With OR, ts_rank still ranks
--     articles that match more of the words higher.
--   * returns article fields (title, publisher, date, url) so the app can cite sources.
--   * hybrid keyword pool is ordered before its limit (the RAG version limited an
--     unordered set, so it could keep any 20 matches instead of the best 20).
--
-- These are SECURITY INVOKER functions (the default), so they run with the caller's
-- rights: the website's anon key can only read, exactly like a normal select.

-- Helper: natural-language question -> OR tsquery. "hiring in Hyderabad" -> 'hire' | 'hyderabad'
create or replace function or_tsquery(query_text text)
returns tsquery
language sql immutable as $$
    select nullif(replace(plainto_tsquery('english', query_text)::text, ' & ', ' | '), '')::tsquery;
$$;

-- ---------------------------------------------------------------------------
-- Semantic: cosine distance on the Voyage embedding.
-- ---------------------------------------------------------------------------
create or replace function article_semantic_search(
    query_embedding vector(1024),
    match_count int default 5
)
returns table (
    id bigint, gcc_id bigint, url text, title text, publisher text,
    published_at date, content text, score float
)
language sql stable as $$
    select id, gcc_id, url, title, publisher, published_at, content,
           1 - (embedding <=> query_embedding) as score
    from articles
    where embedding is not null
    order by embedding <=> query_embedding
    limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Keyword: full-text rank over the generated `fts` column (title + body).
-- ---------------------------------------------------------------------------
create or replace function article_keyword_search(
    query_text text,
    match_count int default 5
)
returns table (
    id bigint, gcc_id bigint, url text, title text, publisher text,
    published_at date, content text, score float
)
language sql stable as $$
    select id, gcc_id, url, title, publisher, published_at, content,
           ts_rank(fts, or_tsquery(query_text)) as score
    from articles
    where fts @@ or_tsquery(query_text)
    order by score desc
    limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Hybrid: Reciprocal Rank Fusion. Rank each list on its own, then score each
-- article by sum of 1/(rrf_k + rank). Scale-free, so cosine and ts_rank can't
-- drown each other out. Pull a wider pool (match_count * 4) from each side first.
-- ---------------------------------------------------------------------------
create or replace function article_hybrid_search(
    query_text text,
    query_embedding vector(1024),
    match_count int default 5,
    rrf_k int default 60
)
returns table (
    id bigint, gcc_id bigint, url text, title text, publisher text,
    published_at date, content text, score float
)
language sql stable as $$
    with sem as (
        select id, row_number() over (order by embedding <=> query_embedding) as rnk
        from articles
        where embedding is not null
        order by embedding <=> query_embedding
        limit match_count * 4
    ),
    kw as (
        select id, row_number() over (
                 order by ts_rank(fts, or_tsquery(query_text)) desc
               ) as rnk
        from articles
        where fts @@ or_tsquery(query_text)
        order by rnk                      -- fix vs RAG version: limit without order by kept arbitrary rows
        limit match_count * 4
    ),
    fused as (
        select coalesce(sem.id, kw.id) as id,
               coalesce(1.0 / (rrf_k + sem.rnk), 0)
             + coalesce(1.0 / (rrf_k + kw.rnk), 0) as score
        from sem
        full outer join kw on sem.id = kw.id
    )
    select a.id, a.gcc_id, a.url, a.title, a.publisher, a.published_at, a.content, f.score
    from fused f
    join articles a on a.id = f.id
    order by f.score desc
    limit match_count;
$$;
