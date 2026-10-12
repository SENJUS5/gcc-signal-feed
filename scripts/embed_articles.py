"""
embed_articles.py: create Voyage embeddings for every article that doesn't have one yet.
Used later by the Ask box (hybrid search). Safe to re-run.
Run from the project root:  python scripts/embed_articles.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db import get_client       # noqa: E402
from lib.embed import embed_texts   # noqa: E402


def main() -> None:
    db = get_client(write=True)
    todo = (db.table("articles").select("id,title,content")
              .is_("embedding", "null").order("id").execute().data)
    print(f"Articles to embed: {len(todo)}")
    if not todo:
        return

    # Title + body, so a search for the headline wording also matches.
    vectors = embed_texts([f"{a['title'] or ''}\n\n{a['content']}" for a in todo])
    for a, vec in zip(todo, vectors):
        db.table("articles").update({"embedding": vec}).eq("id", a["id"]).execute()
    print(f"Embedded {len(vectors)} articles.")


if __name__ == "__main__":
    main()
