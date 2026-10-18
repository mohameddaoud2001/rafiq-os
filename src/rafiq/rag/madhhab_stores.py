"""
RAG retriever protocol + madhhab stores.
Four physically separate SQLite FTS5 indexes.
"""

import json
import math
import pathlib
import sqlite3
from typing import Dict, List, Optional

from pydantic import BaseModel

from rafiq.rag.arabic import normalize_for_search

DB_DIR = pathlib.Path("data/db")
DB_DIR.mkdir(parents=True, exist_ok=True)


class Passage(BaseModel):
    id: str
    madhhab: str
    work: Optional[str] = None
    author: Optional[str] = None
    edition: Optional[str] = None
    volume: Optional[int] = None
    page: Optional[int] = None
    text: str
    topic_tags: List[str] = []
    mutamad: Optional[bool] = None
    verified: bool = False
    provenance: Optional[str] = None
    license: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None


def get_db_path(madhhab: str) -> pathlib.Path:
    return DB_DIR / f"{madhhab}.db"


def init_db(madhhab: str):
    db_path = get_db_path(madhhab)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS passages")
    cur.execute("DROP TABLE IF EXISTS passages_fts")
    cur.execute("""
        CREATE TABLE passages (
            id TEXT PRIMARY KEY,
            madhhab TEXT,
            work TEXT,
            author TEXT,
            edition TEXT,
            volume INTEGER,
            page INTEGER,
            text TEXT,
            topic_tags TEXT,
            mutamad INTEGER,
            verified INTEGER,
            provenance TEXT,
            license TEXT,
            verified_by TEXT,
            verified_at TEXT,
            normalized TEXT
        )
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE passages_fts USING fts5(
            id, text, topic_tags, normalized, content='passages', content_rowid='rowid'
        )
    """)
    conn.commit()
    conn.close()


def _insert_passage_conn(conn, passage: Passage):
    cur = conn.cursor()
    normalized = normalize_for_search(passage.text + " " + " ".join(passage.topic_tags))
    cur.execute(
        """
        INSERT OR REPLACE INTO passages
        (id, madhhab, work, author, edition, volume, page, text, topic_tags,
         mutamad, verified, provenance, license, verified_by, verified_at, normalized)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
        (
            passage.id,
            passage.madhhab,
            passage.work,
            passage.author,
            passage.edition,
            passage.volume,
            passage.page,
            passage.text,
            json.dumps(passage.topic_tags, ensure_ascii=False),
            1 if passage.mutamad else (0 if passage.mutamad is False else None),
            1 if passage.verified else 0,
            passage.provenance,
            passage.license,
            passage.verified_by,
            passage.verified_at,
            normalized,
        ),
    )
    cur.execute(
        """
        INSERT OR REPLACE INTO passages_fts (rowid, id, text, topic_tags, normalized)
        VALUES (
            (SELECT rowid FROM passages WHERE id=?),
            ?, ?, ?, ?
        )
    """,
        (
            passage.id,
            passage.id,
            passage.text,
            json.dumps(passage.topic_tags, ensure_ascii=False),
            normalized,
        ),
    )


def insert_passage(madhhab: str, passage: Passage):
    db_path = get_db_path(madhhab)
    conn = sqlite3.connect(db_path)
    _insert_passage_conn(conn, passage)
    conn.commit()
    conn.close()


MADHHABS = ["maliki", "shafii", "hanafi", "hanbali"]

_PASSAGE_COLS = (
    "id, madhhab, work, author, edition, volume, page, text, topic_tags, "
    "mutamad, verified, provenance, license, verified_by, verified_at"
)


def _row_to_passage(r) -> Passage:
    return Passage(
        id=r[0],
        madhhab=r[1],
        work=r[2],
        author=r[3],
        edition=r[4],
        volume=r[5],
        page=r[6],
        text=r[7],
        topic_tags=json.loads(r[8]) if r[8] else [],
        mutamad=bool(r[9]) if r[9] is not None else None,
        verified=bool(r[10]),
        provenance=r[11],
        license=r[12],
        verified_by=r[13],
        verified_at=r[14],
    )


_AR_STOPWORDS = {
    "ما",
    "هل",
    "في",
    "من",
    "على",
    "عن",
    "الى",
    "غير",
    "لا",
    "لم",
    "لن",
    "ان",
    "كان",
    "كانت",
    "هذا",
    "هذه",
    "ذلك",
    "تلك",
    "ثم",
    "قد",
    "كل",
    "بعد",
    "قبل",
    "عند",
    "حتى",
    "اذا",
    "او",
    "و",
}

_AR_PREFIXES = ("وال", "فال", "بال", "كال", "ال", "و", "ف", "ب", "ل", "ك")


def _strip_prefix(tok: str) -> str:
    for pref in _AR_PREFIXES:
        if tok.startswith(pref) and len(tok) - len(pref) >= 3:
            return tok[len(pref) :]
    return tok


def query_cores(text: str) -> List[str]:
    """Content-word cores for the relaxed fallback.

    Arabic glues articles and particles onto words (والوقوف، بعرفة), so exact
    FTS tokens miss valid matches. Cores are matched as substrings instead.
    """
    normalized_q = normalize_for_search(text)
    cores: List[str] = []
    for tok in normalized_q.split():
        if len(tok) < 3 or tok in _AR_STOPWORDS:
            continue
        core = _strip_prefix(tok)
        if core not in cores:
            cores.append(core)
    return cores


def _query_cores(normalized_q: str) -> List[str]:
    return query_cores(normalized_q)


def _score_row(row, cores: List[str], idf: Dict[str, float]) -> tuple:
    """(score, tag_hits, matched_cores) for one passage row.

    Tags are curated topic anchors: an exact tag-core match counts 3x IDF,
    a substring tag match 2x, text occurrences at most 3x1 each. Matching more
    distinct cores adds a coverage bonus.
    """
    tags_norm = normalize_for_search(" ".join(json.loads(row[8]) if row[8] else []))
    tag_cores = {_strip_prefix(tok) for tok in tags_norm.split()}
    text_norm = normalize_for_search(row[7])
    tag_hits = 0
    score = 0.0
    matched = 0
    for c in cores:
        weight = 0.0
        if c in tag_cores:
            weight += 3.0 * idf[c]
            tag_hits += 1
        elif c in tags_norm:
            weight += 2.0 * idf[c]
            tag_hits += 1
        occ = text_norm.count(c)
        if occ:
            weight += min(3, occ) * idf[c]
        if weight:
            matched += 1
            score += weight
    if matched > 1:
        score *= 1.0 + 0.15 * (matched - 1)
    return score, tag_hits, matched


def _ranked_core_search(
    cur, normalized_q: str, limit: int, verified_clause_plain: str, strict_ids: set
) -> list:
    """IDF-weighted, tag-anchored ranking over rows matching any core.

    Rows that matched the strict FTS AND keep their place even without a tag
    hit (all cores present in the text is strong evidence); every other row
    needs at least one curated tag anchor so off-topic pages stay out. Strict
    rows get a small precision bonus. Rare cores (نصاب، خلع) outweigh generic
    ones (صلاة، حكم) via IDF.
    """
    cores = _query_cores(normalized_q)
    if not cores:
        return []
    count_clause = verified_clause_plain.replace("verified", "passages.verified")
    total = max(
        1, cur.execute(f"SELECT COUNT(*) FROM passages WHERE 1=1 {count_clause}").fetchone()[0]
    )
    idf: Dict[str, float] = {}
    for c in cores:
        df = cur.execute(
            f"SELECT COUNT(*) FROM passages WHERE normalized LIKE ? {count_clause}",
            (f"%{c}%",),
        ).fetchone()[0]
        idf[c] = 1.0 + math.log(total / (1.0 + df))
    where = " OR ".join(["normalized LIKE ?"] * len(cores))
    cur.execute(
        f"SELECT {_PASSAGE_COLS} FROM passages WHERE ({where}) {verified_clause_plain} LIMIT 2000",
        [f"%{c}%" for c in cores],
    )
    scored = []
    for r in cur.fetchall():
        score, tag_hits, _matched = _score_row(r, cores, idf)
        if not score:
            continue
        if r[0] in strict_ids:
            score *= 1.05
        elif not tag_hits:
            continue
        scored.append((score, r))
    scored.sort(key=lambda t: (-t[0], t[1][0]))
    return [r for _, r in scored[:limit]]


def search_passages(
    madhhab: str, query: str, limit: int = 5, threshold: float = 0.0, verified_only: bool = False
) -> List[Passage]:
    db_path = get_db_path(madhhab)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    normalized_q = normalize_for_search(query)
    verified_clause = "AND p.verified = 1" if verified_only else ""
    verified_clause_plain = "AND verified = 1" if verified_only else ""
    # Strict FTS5 AND first (BM25 just to pick the candidate pool)...
    strict_rows = []
    try:
        cur.execute(
            f"""
            SELECT p.id, p.madhhab, p.work, p.author, p.edition, p.volume, p.page,
                   p.text, p.topic_tags, p.mutamad, p.verified, p.provenance,
                   p.license, p.verified_by, p.verified_at
            FROM passages_fts
            JOIN passages p ON passages_fts.rowid = p.rowid
            WHERE passages_fts MATCH ? {verified_clause}
            ORDER BY rank
            LIMIT 40
        """,
            (normalized_q,),
        )
        strict_rows = cur.fetchall()
    except sqlite3.OperationalError:
        # fallback to LIKE (exact phrase)
        cur.execute(
            f"""
            SELECT {_PASSAGE_COLS}
            FROM passages WHERE normalized LIKE ? {verified_clause_plain} LIMIT 40
        """,
            (f"%{normalized_q}%",),
        )
        strict_rows = cur.fetchall()
    # ...then re-rank strict rows + tag-anchored candidates with one IDF scorer.
    rows = _ranked_core_search(
        cur, normalized_q, limit, verified_clause_plain, strict_ids={r[0] for r in strict_rows}
    )
    if not rows and strict_rows:
        # query with no usable cores (all stopwords): keep the FTS order
        rows = strict_rows[:limit]
    conn.close()
    return [_row_to_passage(r) for r in rows]


def get_passage(madhhab: str, passage_id: str) -> Optional[Passage]:
    db_path = get_db_path(madhhab)
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        f"SELECT {_PASSAGE_COLS} FROM passages WHERE id = ?", (passage_id,)
    ).fetchone()
    conn.close()
    return _row_to_passage(row) if row else None


def list_passages(madhhab: str, verified: Optional[bool] = None, limit: int = 200) -> List[Passage]:
    db_path = get_db_path(madhhab)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    sql = f"SELECT {_PASSAGE_COLS} FROM passages"
    params: list = []
    if verified is not None:
        sql += " WHERE verified = ?"
        params.append(1 if verified else 0)
    sql += " ORDER BY id LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_row_to_passage(r) for r in rows]


def search_all_madhhabs(
    query: str, limit_per: int = 3, verified_only: bool = False
) -> Dict[str, List[Passage]]:
    result = {}
    for madhhab in MADHHABS:
        result[madhhab] = search_passages(
            madhhab, query, limit=limit_per, verified_only=verified_only
        )
    return result


def _load_seed_file(madhhab: str, seed_path: pathlib.Path):
    with open(seed_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            p = Passage(**data)
            # Enforce rule: verified:false must have volume null, page null
            if not p.verified:
                if p.volume is not None or p.page is not None:
                    # fix per spec
                    p.volume = None
                    p.page = None
            insert_passage(madhhab, p)


def load_seed_data():
    """Reset and load seed.jsonl from data/corpus/*/seed.jsonl into DBs (tests/demo)."""
    corpus_root = pathlib.Path("data/corpus")
    for madhhab in ["maliki", "shafii", "hanafi", "hanbali"]:
        init_db(madhhab)
        seed_path = corpus_root / madhhab / "seed.jsonl"
        if not seed_path.exists():
            continue
        _load_seed_file(madhhab, seed_path)


def sync_candidates() -> int:
    """Additively load data/corpus/*/candidates/*.jsonl.

    Real digitized text awaiting scholar sign-off. Never overwrites existing
    passages, so scholar sign-offs (verified rows) are never clobbered.
    """
    from rafiq.rag.ingest import validate_passage

    corpus_root = pathlib.Path("data/corpus")
    added = 0
    for madhhab in MADHHABS:
        cand_dir = corpus_root / madhhab / "candidates"
        if not cand_dir.is_dir():
            continue
        if not get_db_path(madhhab).exists():
            init_db(madhhab)
        conn = sqlite3.connect(get_db_path(madhhab))
        existing = {row[0] for row in conn.execute("SELECT id FROM passages")}
        try:
            for path in sorted(cand_dir.glob("*.jsonl")):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        p = validate_passage(json.loads(line))
                        if p.id in existing:
                            continue
                        _insert_passage_conn(conn, p)
                        existing.add(p.id)
                        added += 1
            conn.commit()
        finally:
            conn.close()
    return added


def ensure_corpus_loaded():
    """Startup helper: seed if a store is empty, then sync candidates additively."""
    corpus_root = pathlib.Path("data/corpus")
    for madhhab in MADHHABS:
        db_path = get_db_path(madhhab)
        empty = True
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT COUNT(*) FROM passages").fetchone()
                empty = row[0] == 0
            except sqlite3.OperationalError:
                empty = True
            conn.close()
        if empty:
            init_db(madhhab)
            seed_path = corpus_root / madhhab / "seed.jsonl"
            if seed_path.exists():
                _load_seed_file(madhhab, seed_path)
    return sync_candidates()
