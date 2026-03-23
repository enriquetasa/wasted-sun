"""
Hardening for values taken from environment and passed to PostgreSQL.
Identifiers are never interpolated as raw strings — only via psycopg.sql.Identifier
after passing these checks.
"""

from __future__ import annotations

import re

# Unquoted PostgreSQL identifier: letter or underscore first, then alnum + underscore.
_IDENT_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Optional qualified name: schema.table (one dot max).
_MAX_IDENT_LEN = 128

_FORBIDDEN_IN_AS_OF = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE|CALL|"
    r"PREPARE|LISTEN|NOTIFY|SET\s+ROLE|SET\s+SESSION"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)


def validate_pg_identifier(name: str, *, label: str = "identifier") -> str:
    s = name.strip()
    if not s or len(s) > _MAX_IDENT_LEN:
        raise ValueError(f"invalid {label}: empty or too long")
    if not _IDENT_PART.match(s):
        raise ValueError(f"invalid {label}: only letters, digits, underscore; must start with letter or _")
    return s


def validate_pg_qualified_table(name: str, *, label: str = "table") -> str:
    """Allow `table` or `schema.table` (single schema qualifier)."""
    s = name.strip()
    if not s or len(s) > _MAX_IDENT_LEN * 2 + 1:
        raise ValueError(f"invalid {label}")
    parts = s.split(".")
    if len(parts) > 2:
        raise ValueError(f"invalid {label}: at most one schema qualifier (schema.table)")
    for p in parts:
        validate_pg_identifier(p, label=label)
    return s


def validate_as_of_select(query: str) -> str:
    """
    Legacy escape hatch: single SELECT only, no stacked statements.
    Prefer WASTED_SUN_PG_AS_OF_META_TABLE + COLUMN instead.
    """
    s = query.strip()
    if not s:
        raise ValueError("as_of query empty")
    if len(s) > 2048:
        raise ValueError("as_of query too long")
    if ";" in s:
        raise ValueError("as_of query must not contain semicolons")
    if "--" in s or "/*" in s or "*/" in s:
        raise ValueError("as_of query must not contain SQL comments")
    if not re.match(r"^SELECT\s+", s, re.IGNORECASE):
        raise ValueError("as_of query must start with SELECT")
    if _FORBIDDEN_IN_AS_OF.search(s):
        raise ValueError("as_of query contains forbidden keyword")
    return s


def validate_qh_slots(n: int) -> int:
    if n < 1 or n > 200:
        raise ValueError("WASTED_SUN_PG_QH_SLOTS must be between 1 and 200")
    return n


# Hostname for Plausible `data-domain` (no spaces, no quotes).
_PLAUSIBLE_HOST = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)


def validate_plausible_domain(host: str) -> str:
    h = host.strip()
    if not h:
        return ""
    if len(h) > 253 or not _PLAUSIBLE_HOST.match(h):
        raise ValueError("PLAUSIBLE_DOMAIN must look like a valid hostname")
    return h


def validate_plausible_script_url(url: str) -> str:
    u = url.strip()
    if not u:
        return ""
    if len(u) > 512 or not u.startswith(("https://", "http://")):
        raise ValueError("PLAUSIBLE_SCRIPT_URL must be an http(s) URL")
    if any(c in u for c in ('"', "'", "<", ">", "\n", "\r")):
        raise ValueError("PLAUSIBLE_SCRIPT_URL contains invalid characters")
    return u
