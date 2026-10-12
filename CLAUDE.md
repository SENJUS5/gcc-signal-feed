# Project: GCC Signal Feed (Flexiple take-home assignment)

Read this fully before doing anything. It explains the assignment, how we got to the decision, what we're building, and the plan.

## 1. The assignment
Flexiple, a Bengaluru hiring company that also sets up GCCs in India, gave me a take-home assignment. They want:
1. A deck covering: the problem, the opportunities, the solution (what to build and for whom first), and the positioning.
2. A working prototype of the solution, showing AI product-building skills. It doesn't need to be complete. It needs to work.
Ground rules: use a lot of AI, but no thoughtless AI output. They care about both thinking and looks.
Deadline: Monday night, 12 Oct 2026. We started Sunday 11 Oct around noon.
You (Claude Code) will help with the prototype only. I'm doing the deck separately.

## 2. Background, in simple words
- A GCC (Global Capability Centre) is a foreign company's own office in India that works only for that company. Example: Walmart's tech centre in Bengaluru. It's not outsourcing.
- India has around 2,000+ GCCs. A GCC goes through 4 stages: Set up, Run, Grow, Mature.
- The problem: GCC data is scattered and nobody trusts it. GCC counts don't match across reports (2,117 vs 1,700+ vs 536). Lists are static and miss closures. Many advisors also sell services, so they aren't neutral.
- Players: foreign companies, existing GCCs, service providers (recruiters, real estate, payroll, lawyers, setup firms), job seekers, state governments.

## 3. How we reached the decision
- First idea, dropped: a "city picker" tool for foreign companies setting up their first GCC. Dropped because only about 100 new GCCs open a year, it's a one-time decision, and these companies trust human advisors.
- Then we compared 9 personas by how often the pain comes, number of users, willingness to pay, and ease of building. We picked two:
  - Service providers: weekly pain ("who should I sell to next?"), and they already pay for GCC lists.
  - Job seekers: they check companies with every job offer ("is this a real GCC, is it safe, what does it pay?").
- Then we studied Flexiple. Flexiple is itself a service provider: it sells contractors, managed teams ($299/person/month), and full GCC setup. It already has a public GCC directory (536 verified GCCs, each with a source, last updated Aug 2026), new GCCs tracked by hand, and a talent database of about 98M profiles. Its GCC pages exist to bring in company clients.
- So Flexiple needs more GCC clients, found earlier. That decided the priority.

## 4. The locked decision
- P0, GCC Signal Feed (MAIN SCREEN): a weekly feed of GCC changes in India: new centre, expansion, hiring push, office lease, layoffs or closure. Each signal has company, city, signal type, date, a one-line summary, a source link, and a strength score from 1 to 5. User: Flexiple's own GCC sales team.
- P1, Company Check: click any company in the feed to open a card: is it a real GCC, is it growing or shrinking (from public signals only), and its recent signals. User: job seekers.
- Later (not in prototype): sell the feed to providers who don't compete with Flexiple, like real estate firms and lawyers.
- Bonus if time: an "Ask a question" box that answers from stored articles, with sources, using my existing RAG hybrid search.

The two users see different amounts, so competitors can't just sign up as job seekers and get the leads:
- Job seeker view: one company at a time, by search. Shows "growing" or "shrinking", no exact numbers, no strength scores, no full list, no alerts.
- Sales team view: the full feed, strength scores, weekly changes, and a suggested next action.
For the prototype, a simple toggle between the two views is enough. No real login needed.

## 5. Tech stack (all Python, I'm not strong in JavaScript)
- Website: Streamlit, deployed on Streamlit Community Cloud for a free live link
- Database: Supabase (Postgres + pgvector)
- AI: Gemini API free tier (key from Google AI Studio). No paid APIs, and no Anthropic API key. Use Gemini to read news articles and pull out structured signals, and for the Ask box. Backup if Gemini hits its limit: Ollama on my laptop, for article reading only.
- Signal extraction runs once on my laptop and saves results to Supabase. The live website only reads from Supabase. Only the Ask box calls the AI live.
- Handle free-tier rate limits: add retries with a short wait, and don't re-process articles already done.
- Search: Voyage embeddings + hybrid search (semantic + keyword with Reciprocal Rank Fusion), reused from my RAG project:
  https://github.com/SENJUS5/multimodal-rag-project
- Clone that repo into a separate "reference" folder. Copy only the parts we need into this new project. Don't change the original repo.
- From my RAG project, reuse: Supabase schema patterns (sql/01_schema.sql), hybrid search functions (sql/02_search_fns.sql), Voyage embedding code (ingest/core.py), the link loader (ingest/loaders/doc_loaders.py), search code (ingest/retrieval.py), and content-hash de-duplication.
- Don't use: the MCP server (server.py), code chunking (ingest/loaders/code_loader.py), or Ollama image captioning.

## 6. Data rules
- 20 to 30 GCCs, with news from the last 60 to 90 days
- Mix of new, expanding, and shrinking or closing centres
- Public sources only. Every signal must link to its source.
- Never invent data. We don't have access to Flexiple's private talent data, so any sample numbers must be clearly labelled "sample".

## 7. Plan and timeline
- Sunday afternoon to evening: setup, database, collect news
- Sunday night: AI signal extraction script, then the Feed screen
- Monday morning: Company Check card, Ask box if time, polish, deploy
- Monday afternoon and evening: I work on the deck, then final testing and submit

Build steps, one at a time:
1. Setup and database
2. Collect news articles for 20 to 30 GCCs
3. AI script: article in, structured signal out, saved to Supabase
4. Feed screen in Streamlit (filter by city, signal type, date)
5. Company Check card
6. Ask box using RAG search (if time)
7. Deploy and get the live link

## 8. How to work with me
- Write all the code. I understand logic and can spot bugs, but explain each step in simple words.
- Before running a command or installing a package, tell me in one line what it does.
- Do one step at a time. Stop after each step and wait for me.
- Ask me before any big decision. Max one question at a time.
- Never put API keys in code files. Keep them in .env, and make sure .env is in .gitignore.
- Keep the design clean and simple. Looks matter for this assignment.

## 9. Start now: Step 1 only
1. Look at my RAG project and tell me which files we can reuse.
2. Propose a simple folder structure.
3. Write the Supabase SQL for three tables: gccs, articles, signals.
4. List the setup steps: packages to install and the keys needed in .env.
Stop after Step 1 and wait for me.