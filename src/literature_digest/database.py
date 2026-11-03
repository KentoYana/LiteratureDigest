"""Transactional storage. PRAGMA user_version is the migration version."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .normalizer import identities


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


MIGRATIONS = {
    1: """
CREATE TABLE feeds (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL,
 category TEXT NOT NULL DEFAULT '', etag TEXT, modified TEXT, last_fetch TEXT, error TEXT
);
CREATE TABLE articles (
 id INTEGER PRIMARY KEY, guid TEXT UNIQUE NOT NULL,
 title TEXT NOT NULL DEFAULT '', authors TEXT NOT NULL DEFAULT '',
 journal TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '',
 doi TEXT NOT NULL DEFAULT '', doi_raw TEXT NOT NULL DEFAULT '', pmid TEXT NOT NULL DEFAULT '',
 url TEXT NOT NULL DEFAULT '', abstract TEXT NOT NULL DEFAULT '',
 title_ja TEXT, body_ja TEXT, model TEXT, prompt_version TEXT, generated_at TEXT,
 status TEXT NOT NULL DEFAULT 'pending'
 CHECK(status IN ('pending','processing','completed','skipped','failed')),
 error TEXT, attempts INTEGER NOT NULL DEFAULT 0, metadata_checked INTEGER NOT NULL DEFAULT 0,
 fetched_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE identities (key TEXT PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES articles(id));
CREATE TABLE entries (
 id INTEGER PRIMARY KEY, feed_id TEXT NOT NULL REFERENCES feeds(id),
 source_id TEXT NOT NULL, article_id INTEGER NOT NULL REFERENCES articles(id),
 metadata_json TEXT NOT NULL, fetched_at TEXT NOT NULL, UNIQUE(feed_id, source_id)
);
CREATE TABLE api_calls (
 id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES articles(id),
 called_at TEXT NOT NULL, model TEXT NOT NULL, outcome TEXT NOT NULL, usage_json TEXT
);
CREATE INDEX article_status ON articles(status);
CREATE INDEX entry_article ON entries(article_id);
"""
}


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > max(MIGRATIONS):
            self.close()
            raise ValueError("DBは新しいバージョンです。アプリをアップデートしてください")
        for target, sql in sorted(MIGRATIONS.items()):
            if target > version:
                # Schema and version commit together; future migrations go here.
                self.conn.executescript(
                    f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version={target};\nCOMMIT;"
                )

    def close(self):
        self.conn.close()

    def sync_feeds(self, feeds):
        with self.conn:
            self.conn.execute("UPDATE feeds SET enabled=0")
            for f in feeds:
                self.conn.execute(
                    """INSERT INTO feeds(id,name,url,enabled,category) VALUES(?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url,
                 enabled=excluded.enabled,category=excluded.category,
                 etag=CASE WHEN feeds.url=excluded.url THEN feeds.etag END,
                 modified=CASE WHEN feeds.url=excluded.url THEN feeds.modified END""",
                    (f["id"], f["name"], f["url"], f.get("enabled", True), f.get("category", "")),
                )

    def ingest(self, paper, feed_id, source_id):
        keys = identities(paper, feed_id, source_id)
        stamp = now()
        with self.conn:
            candidate = None
            for key in keys:
                row = self.conn.execute(
                    """SELECT a.* FROM articles a JOIN identities i
                    ON a.id=i.article_id WHERE i.key=?""",
                    (key,),
                ).fetchone()
                if row is None:
                    continue
                if paper.get("doi") and row["doi"] and paper["doi"] != row["doi"]:
                    continue
                if paper.get("pmid") and row["pmid"] and paper["pmid"] != row["pmid"]:
                    continue
                candidate = row
                break
            is_new = candidate is None
            fields = [
                "title",
                "authors",
                "journal",
                "published",
                "doi",
                "doi_raw",
                "pmid",
                "url",
                "abstract",
            ]
            if is_new:
                cur = self.conn.execute(
                    f"INSERT INTO articles(guid,{','.join(fields)},fetched_at,updated_at) "
                    f"VALUES({','.join('?' for _ in range(len(fields) + 3))})",
                    (
                        "urn:uuid:" + str(uuid.uuid4()),
                        *(paper.get(f, "") for f in fields),
                        stamp,
                        stamp,
                    ),
                )
                article_id = cur.lastrowid
            else:
                article_id = candidate["id"]
                # Enrich missing fields without changing the original title, URL, DOI or article.
                for field in fields:
                    if not candidate[field] and paper.get(field):
                        self.conn.execute(
                            f"UPDATE articles SET {field}=?,updated_at=? WHERE id=?",
                            (paper[field], stamp, article_id),
                        )
                if paper.get("abstract") and candidate["status"] == "skipped":
                    self.conn.execute(
                        "UPDATE articles SET status='pending',error=NULL WHERE id=?", (article_id,)
                    )
            for key in keys:
                self.conn.execute(
                    "INSERT OR IGNORE INTO identities(key,article_id) VALUES(?,?)",
                    (key, article_id),
                )
            self.conn.execute(
                """INSERT INTO entries(feed_id,source_id,article_id,metadata_json,fetched_at)
              VALUES(?,?,?,?,?) ON CONFLICT(feed_id,source_id) DO UPDATE SET
              article_id=excluded.article_id,metadata_json=excluded.metadata_json""",
                (feed_id, source_id, article_id, json.dumps(paper, ensure_ascii=False), stamp),
            )
        return article_id, is_new

    def recover(self):
        # Caller holds the process flock, so no live worker can own these rows.
        with self.conn:
            self.conn.execute(
                "UPDATE articles SET status='pending',error='interrupted' WHERE status='processing'"
            )

    def pending(self, limit):
        return self.conn.execute(
            """SELECT * FROM articles WHERE status IN ('pending','failed')
            ORDER BY attempts,fetched_at,id LIMIT ?""",
            (limit,),
        ).fetchall()

    def update(self, article_id, **fields):
        allowed = {
            "status",
            "error",
            "abstract",
            "metadata_checked",
            "title_ja",
            "body_ja",
            "model",
            "prompt_version",
            "generated_at",
        }
        if not fields or set(fields) - allowed:
            raise ValueError("Invalid database update")
        fields["updated_at"] = now()
        with self.conn:
            self.conn.execute(
                f"UPDATE articles SET {','.join(k + '=?' for k in fields)} WHERE id=?",
                (*fields.values(), article_id),
            )

    def claim(self, article_id):
        with self.conn:
            self.conn.execute(
                "UPDATE articles SET status='processing',attempts=attempts+1,error=NULL WHERE id=?",
                (article_id,),
            )

    def api_call(self, article_id, model, outcome, usage):
        with self.conn:
            self.conn.execute(
                "INSERT INTO api_calls(article_id,called_at,model,outcome,usage_json) VALUES(?,?,?,?,?)",
                (article_id, now(), model, outcome, json.dumps(usage) if usage else None),
            )

    def status(self):
        counts = {k: 0 for k in ["pending", "processing", "completed", "skipped", "failed"]}
        counts.update(
            dict(self.conn.execute("SELECT status,count(*) FROM articles GROUP BY status"))
        )
        return {
            "articles": counts,
            "feeds": self.conn.execute("SELECT count(*) FROM feeds WHERE enabled=1").fetchone()[0],
            "feed_errors": self.conn.execute(
                "SELECT count(*) FROM feeds WHERE error IS NOT NULL AND enabled=1"
            ).fetchone()[0],
            "api_calls": self.conn.execute("SELECT count(*) FROM api_calls").fetchone()[0],
            "schema_version": self.conn.execute("PRAGMA user_version").fetchone()[0],
        }

    def published(self, limit):
        return self.conn.execute(
            """SELECT * FROM articles WHERE status IN ('completed','skipped')
            ORDER BY COALESCE(NULLIF(published,''),fetched_at) DESC,id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
