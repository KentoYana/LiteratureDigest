"""Generate only unprocessed, abstract-backed papers, with bounded recovery."""

import hashlib
import logging

from .config import template
from .credentials import api_key
from .database import now
from .metadata import PubMed
from .network import AuthenticationError, NetworkError
from .sarashina import OutputError, Sarashina

log = logging.getLogger(__name__)


def load_prompt(paths):
    custom = paths.config / "digest.md"
    prompt = (
        custom.read_text(encoding="utf-8") if custom.exists() else template("prompts/digest.md")
    )
    if not prompt.strip():
        raise ValueError("記事生成プロンプトが空です")
    return prompt, "v1-sha256:" + hashlib.sha256(prompt.encode()).hexdigest()


def generate(db, paths, settings, limit=None, client_factory=None, metadata=None):
    db.recover()
    stats = {"completed": 0, "skipped": 0, "failed": 0, "api_calls": 0}
    rows = db.pending(limit if limit is not None else settings["llm"]["batch_limit"])
    if not rows:
        return stats
    prompt, version = load_prompt(paths)
    metadata = metadata or PubMed(settings["metadata"]["email"])
    key = None
    for original in rows:
        paper = dict(original)
        article_id = paper["id"]
        db.claim(article_id)
        try:
            if (
                not paper["abstract"]
                and not paper["metadata_checked"]
                and settings["metadata"]["pubmed"]
            ):
                paper["abstract"] = metadata.abstract(paper)
                db.update(article_id, abstract=paper["abstract"], metadata_checked=1)
            if not paper["abstract"]:
                db.update(article_id, status="skipped", error="no_abstract")
                stats["skipped"] += 1
                continue

            def observe(outcome, usage):
                db.api_call(article_id, settings["llm"]["model"], outcome, usage)
                stats["api_calls"] += 1

            if client_factory:
                client = client_factory(observe)
            else:
                if key is None:
                    key = api_key()
                client = Sarashina(key, settings["llm"], observer=observe)
            try:
                digest = client.generate(paper, prompt)
            except OutputError as exc:
                if exc.code != "invalid_length":
                    raise
                # At most one editorial regeneration, only for length violations.
                digest = client.generate(paper, prompt, correction=True)
            db.update(
                article_id,
                status="completed",
                error=None,
                title_ja=digest.title_ja,
                body_ja=digest.body_ja,
                model=digest.model,
                prompt_version=version,
                generated_at=now(),
            )
            stats["completed"] += 1
            log.info("Article generated id=%s", article_id)
        except (NetworkError, OutputError) as exc:
            db.update(article_id, status="failed", error=exc.code)
            stats["failed"] += 1
            log.warning("Generation failed id=%s error=%s", article_id, exc.code)
            if isinstance(exc, AuthenticationError) or exc.code in {
                "missing_api_key",
                "retry_after_deferred",
            }:
                # Stop this batch on an invalid credential or long server cooldown.
                break
        except Exception:
            db.update(article_id, status="failed", error="internal_generation_error")
            stats["failed"] += 1
            log.error("Generation failed id=%s error=internal_generation_error", article_id)
    log.info("Generation result %s", stats)
    return stats
