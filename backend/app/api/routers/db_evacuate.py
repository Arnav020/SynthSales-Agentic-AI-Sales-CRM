"""TEMPORARY — evacuate the expiring Render Postgres into its new home.

Render cuts external TLS access to an expired free database, so no outside
pg_dump can reach it; only this app (on Render's private network) still can.
This endpoint copies every table into a caller-supplied target Postgres over
the app's own SQLAlchemy stack: schema via ``Base.metadata.create_all``, rows
in FK-safe order, integer-PK sequences realigned, and the ``alembic_version``
stamp carried over so the on-boot ``alembic upgrade head`` is a no-op after
``DATABASE_URL`` is switched to the target.

Gated by the ``MIGRATE_TOKEN`` env var — the route 404s unless the caller
presents the exact token, and 404s for everyone when the var is unset.

DELETE THIS FILE (and its ``main.py`` registration + the env var) once the
migration is verified.
"""

import os
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, delete, insert, select, text

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.core.database import Base, engine as source_engine

router = APIRouter(prefix="/api/_evacuate", tags=["_evacuate"])


class EvacuatePayload(BaseModel):
    target_url: str


def _normalize(url: str) -> str:
    """Same driver rewrite as config.Settings — force the psycopg v3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@router.post("")
def evacuate(
    payload: EvacuatePayload,
    x_migrate_token: str | None = Header(default=None),
) -> dict:
    token = os.environ.get("MIGRATE_TOKEN", "")
    if not token or not secrets.compare_digest(x_migrate_token or "", token):
        raise HTTPException(status_code=404, detail="Not Found")

    target = create_engine(
        _normalize(payload.target_url), pool_pre_ping=True, future=True
    )
    report: dict = {"tables": {}}
    try:
        Base.metadata.create_all(target)
        # REPEATABLE READ gives one consistent snapshot across all the SELECTs
        # even if the scheduler writes mid-copy.
        with source_engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as src, src.begin(), target.begin() as tgt:
            report["source_version"] = src.execute(
                text("show server_version")
            ).scalar()
            report["target_version"] = tgt.execute(
                text("show server_version")
            ).scalar()

            # Wipe the target children-first so re-runs are idempotent.
            for table in reversed(Base.metadata.sorted_tables):
                tgt.execute(delete(table))

            for table in Base.metadata.sorted_tables:
                rows = [dict(r) for r in src.execute(select(table)).mappings()]
                if rows:
                    tgt.execute(insert(table), rows)
                report["tables"][table.name] = len(rows)

            # Realign serial/identity sequences with the copied ids. setval is
            # strict, so a NULL from pg_get_serial_sequence (no sequence) is a
            # harmless no-op.
            pks = [
                (t, list(t.primary_key.columns)[0])
                for t in Base.metadata.sorted_tables
                if len(t.primary_key.columns) == 1
            ]
            for t, col in pks:
                try:
                    if col.type.python_type is not int:
                        continue
                except NotImplementedError:
                    continue
                tgt.execute(
                    text(
                        f'select setval(pg_get_serial_sequence(:t, :c), '
                        f'coalesce((select max("{col.name}") from "{t.name}"), 0) + 1, '
                        f"false)"
                    ),
                    {"t": t.name, "c": col.name},
                )

            ver = src.execute(
                text("select version_num from alembic_version")
            ).scalar()
            if ver:
                tgt.execute(
                    text(
                        "create table if not exists alembic_version ("
                        "version_num varchar(32) not null, "
                        "constraint alembic_version_pkc primary key (version_num))"
                    )
                )
                tgt.execute(text("delete from alembic_version"))
                tgt.execute(
                    text("insert into alembic_version (version_num) values (:v)"),
                    {"v": ver},
                )
            report["alembic_version"] = ver
    finally:
        target.dispose()
    return report
