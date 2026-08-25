import argparse
import asyncio
import getpass
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from pdi.auth.service import ALL_SCOPES, READ_SCOPES, create_api_token, create_user
from pdi.core.config import get_settings
from pdi.core.database import session_factory
from pdi.migration.paperless import (
    PaperlessFixtureSource,
    PaperlessRestSource,
    PaperlessSource,
    analyze,
    dry_run,
    import_documents,
    verify,
)
from pdi.operations.backup import create_backup, restore_backup, verify_backup
from pdi.operations.export import create_export
from pdi.operations.models import ApiToken, LocalUser
from pdi.operations.readiness import readiness
from pdi.search.service import rebuild_search_index, verify_search_index
from pdi.storage.dependencies import get_storage
from pdi.storage.reconcile import reconcile_storage


def output(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def output_secret_once(value: object) -> None:
    """Deliver a newly minted credential once to the invoking interactive CLI."""
    # This is the explicit credential-delivery channel, not application logging.
    # codeql[py/clear-text-logging-sensitive-data]
    print(
        json.dumps(value, indent=2, ensure_ascii=False, default=str)
    )


async def run_reconcile(cleanup: bool, stale_after: int) -> None:
    async with session_factory() as session:
        report = await reconcile_storage(
            session, get_storage(), cleanup=cleanup, stale_after_seconds=stale_after
        )
    output(asdict(report))


async def run_search_maintenance(command: str) -> None:
    async with session_factory() as session:
        report = (
            await rebuild_search_index(session)
            if command == "rebuild"
            else await verify_search_index(session)
        )
    output(asdict(report))


def paperless_source(arguments: argparse.Namespace) -> PaperlessSource:
    settings = get_settings()
    if arguments.fixture:
        return PaperlessFixtureSource(arguments.fixture)
    url = arguments.url or settings.paperless_url
    token_file = arguments.token_file or settings.paperless_token_file
    if not url or not token_file:
        raise ValueError("Paperless URL and token file are required")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Paperless token file is empty")
    return PaperlessRestSource(url, token, verify_tls=not arguments.allow_http)  # gitleaks:allow


async def run_paperless(arguments: argparse.Namespace) -> None:
    source = paperless_source(arguments)
    if arguments.paperless_command == "analyze":
        output(await analyze(source))
        return
    async with session_factory() as session:
        if arguments.paperless_command == "verify":
            output(await verify(source, session, get_storage(), arguments.run_id))
        elif not arguments.execute:
            output(await dry_run(source, session))
        else:
            settings = get_settings()
            fingerprint = hashlib.sha256(
                f"{arguments.url or settings.paperless_url}|{await source.version()}".encode()
            ).hexdigest()
            run = await import_documents(
                source,
                session,
                get_storage(),
                settings,
                configuration_fingerprint=fingerprint,
            )
            output(
                {
                    "migration_run_id": str(run.id),
                    "status": run.status,
                    "documents_discovered": run.documents_discovered,
                    "documents_imported": run.documents_imported,
                    "documents_skipped": run.documents_skipped,
                    "documents_failed": run.documents_failed,
                }
            )


def password_from(arguments: argparse.Namespace) -> str:
    if arguments.password_file:
        return str(arguments.password_file.read_text(encoding="utf-8").rstrip("\r\n"))
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    return first


async def run_user(arguments: argparse.Namespace) -> None:
    async with session_factory() as session:
        if arguments.user_command == "create":
            await create_user(session, arguments.username, password_from(arguments))
            output({"created": True})
        else:
            active_user = await session.scalar(
                select(LocalUser).where(LocalUser.username == arguments.username.casefold())
            )
            if active_user is None:
                raise ValueError("User not found")
            active_user.is_active = False
            await session.commit()
            output({"username": active_user.username, "disabled": True})


async def run_token(arguments: argparse.Namespace) -> None:
    async with session_factory() as session:
        if arguments.token_command == "create":
            expires = (
                datetime.now(UTC) + timedelta(days=arguments.expires_days)
                if arguments.expires_days
                else None
            )
            token, plaintext = await create_api_token(
                session,
                username=arguments.username,
                name=arguments.name,
                scopes=arguments.scope,
                expires_at=expires,
            )
            output_secret_once(
                {
                    "id": str(token.id),
                    "name": token.name,
                    "scopes": token.scopes,
                    "expires_at": token.expires_at,
                    "token": plaintext,
                    "warning": "This plaintext token is shown once and is never stored by PDI.",
                }
            )
        else:
            stored_token = await session.get(ApiToken, arguments.token_id)
            if stored_token is None:
                raise ValueError("Token not found")
            stored_token.revoked_at = datetime.now(UTC)
            await session.commit()
            output({"id": str(stored_token.id), "revoked": True})


async def run_operations(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if arguments.command == "backup" and arguments.backup_command == "verify":
        output(verify_backup(arguments.path))
        return
    async with session_factory() as session:
        if arguments.command == "backup":
            output(
                await create_backup(
                    arguments.path,
                    database_url=settings.database_url,
                    storage=get_storage(),
                    session=session,
                )
            )
        elif arguments.command == "restore":
            output(
                await restore_backup(
                    arguments.path,
                    database_url=settings.database_url,
                    storage=get_storage(),
                    session=session,
                    force=arguments.force,
                )
            )
        elif arguments.command == "export":
            output(await create_export(arguments.path, session=session, storage=get_storage()))
        else:
            output(await readiness(session, get_storage(), settings))


def add_source_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--url")
    command.add_argument("--token-file", type=Path)
    command.add_argument("--fixture", type=Path)
    command.add_argument("--allow-http", action="store_true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pdi")
    commands = root.add_subparsers(dest="command", required=True)
    storage = commands.add_parser("storage", help="Storage maintenance")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    reconcile = storage_commands.add_parser("reconcile", help="Compare storage and database")
    reconcile.add_argument("--cleanup", action="store_true")
    reconcile.add_argument("--stale-after", type=int, default=3600, metavar="SECONDS")
    search = commands.add_parser("search", help="Search index maintenance")
    search_commands = search.add_subparsers(dest="search_command", required=True)
    search_commands.add_parser("rebuild")
    search_commands.add_parser("verify")
    migrate = commands.add_parser("migrate")
    migrate_commands = migrate.add_subparsers(dest="migration_source", required=True)
    paperless = migrate_commands.add_parser("paperless")
    paperless_commands = paperless.add_subparsers(dest="paperless_command")
    analyze_command = paperless_commands.add_parser("analyze")
    add_source_options(analyze_command)
    verify_command = paperless_commands.add_parser("verify")
    verify_command.add_argument("--run-id", type=uuid.UUID, required=True)
    add_source_options(verify_command)
    add_source_options(paperless)
    paperless.add_argument("--execute", action="store_true", help="Mutate PDI; default is dry run")
    user = commands.add_parser("user")
    user_commands = user.add_subparsers(dest="user_command", required=True)
    create = user_commands.add_parser("create")
    create.add_argument("username")
    create.add_argument("--password-file", type=Path)
    disable = user_commands.add_parser("disable")
    disable.add_argument("username")
    token = commands.add_parser("token")
    token_commands = token.add_subparsers(dest="token_command", required=True)
    token_create = token_commands.add_parser("create")
    token_create.add_argument("username")
    token_create.add_argument("name")
    token_create.add_argument("--scope", action="append", choices=ALL_SCOPES, default=READ_SCOPES)
    token_create.add_argument("--expires-days", type=int)
    token_revoke = token_commands.add_parser("revoke")
    token_revoke.add_argument("token_id", type=uuid.UUID)
    backup = commands.add_parser("backup")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser("create")
    backup_create.add_argument("path", type=Path)
    backup_verify = backup_commands.add_parser("verify")
    backup_verify.add_argument("path", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("path", type=Path)
    restore.add_argument("--force", action="store_true")
    export = commands.add_parser("export")
    export.add_argument("path", type=Path)
    commands.add_parser("readiness")
    commands.add_parser("health")
    return root


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "storage":
        asyncio.run(run_reconcile(arguments.cleanup, arguments.stale_after))
    elif arguments.command == "search":
        asyncio.run(run_search_maintenance(arguments.search_command))
    elif arguments.command == "migrate":
        asyncio.run(run_paperless(arguments))
    elif arguments.command == "user":
        asyncio.run(run_user(arguments))
    elif arguments.command == "token":
        asyncio.run(run_token(arguments))
    else:
        asyncio.run(run_operations(arguments))


if __name__ == "__main__":
    main()
