import argparse
import asyncio
import json
from dataclasses import asdict

from pdi.core.database import session_factory
from pdi.search.service import rebuild_search_index, verify_search_index
from pdi.storage.dependencies import get_storage
from pdi.storage.reconcile import reconcile_storage


async def run_reconcile(cleanup: bool, stale_after: int) -> None:
    async with session_factory() as session:
        report = await reconcile_storage(
            session,
            get_storage(),
            cleanup=cleanup,
            stale_after_seconds=stale_after,
        )
    print(json.dumps(asdict(report), indent=2))


async def run_search_maintenance(command: str) -> None:
    async with session_factory() as session:
        if command == "rebuild":
            report = await rebuild_search_index(session)
        else:
            report = await verify_search_index(session)
    print(json.dumps(asdict(report), indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pdi")
    commands = root.add_subparsers(dest="command", required=True)
    storage = commands.add_parser("storage", help="Storage maintenance")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    reconcile = storage_commands.add_parser("reconcile", help="Compare storage and database")
    reconcile.add_argument(
        "--cleanup",
        action="store_true",
        help=(
            "Delete orphaned derived assets and stale temporary files; originals and missing "
            "records are never deleted"
        ),
    )
    reconcile.add_argument("--stale-after", type=int, default=3600, metavar="SECONDS")
    search = commands.add_parser("search", help="Search index maintenance")
    search_commands = search.add_subparsers(dest="search_command", required=True)
    search_commands.add_parser("rebuild", help="Idempotently rebuild all search documents")
    search_commands.add_parser("verify", help="Report missing or stale search documents")
    return root


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "storage" and arguments.storage_command == "reconcile":
        asyncio.run(run_reconcile(arguments.cleanup, arguments.stale_after))
    elif arguments.command == "search":
        asyncio.run(run_search_maintenance(arguments.search_command))


if __name__ == "__main__":
    main()
