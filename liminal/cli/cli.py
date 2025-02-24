#!/usr/bin/env python
from pathlib import Path

import typer
from click import Context
from rich import print
from typer.core import TyperGroup

from liminal.cli.controller import (
    autogenerate_revision_file,
    downgrade_benchling_tenant,
    generate_all_files,
    upgrade_benchling_tenant,
)
from liminal.cli.live_test_dropdown_migration import mock_dropdown_full_migration
from liminal.cli.live_test_entity_schema_migration import (
    mock_entity_schema_full_migration,
)
from liminal.cli.utils import read_local_liminal_dir, update_env_revision_id
from liminal.connection.benchling_service import BenchlingService
from liminal.migrate.revisions_timeline import RevisionsTimeline


class OrderCommands(TyperGroup):
    def list_commands(self, ctx: Context) -> list[str]:
        """Return list of commands in the order the commands are defined."""
        return list(self.commands)


app = typer.Typer(
    name="liminal",
    cls=OrderCommands,
    no_args_is_help=True,
    help="The Liminal CLI allows you to run revisions against different Benchling tenants and keep tenants in sync with dropdowns and schemas defined in code.",
)

LIMINAL_DIR_PATH = Path("liminal")
ENV_FILE_PATH = LIMINAL_DIR_PATH / "env.py"
VERSIONS_DIR_PATH = LIMINAL_DIR_PATH / "versions"


@app.command(
    name="init",
    help="Initializes the working directory to use the Liminal CLI. If liminal/ doesn't exist, a new liminal/versions directory is created with an empty initial revision file and a liminal/env.py file.",
)
def init() -> None:
    try:
        LIMINAL_DIR_PATH.mkdir()
        VERSIONS_DIR_PATH.mkdir()
    except Exception:
        raise Exception(
            "Liminal CLI already initialized. liminal/ already exists. Please delete it before running init."
        )
    new_revision_file_path = RevisionsTimeline(VERSIONS_DIR_PATH).init_versions(
        VERSIONS_DIR_PATH
    )
    revision_id = new_revision_file_path.name.split("_")[0]
    env_file = f"""# This file is auto-generated by Liminal.
# Import the models and dropdowns you want to keep in sync here.
# Instantiate the BenchlingConnection(s) with the correct parameters for your tenant(s).
# There must be a revision_id variable defined for each BenchlingConnection instance. The variable name should match the `current_revision_id_var_name` variable passed into the BenchlingConnection instance.
# The revision_id variable name can also match the format `<tenant_name>_CURRENT_REVISION_ID` / `<tenant_alias>_CURRENT_REVISION_ID`.
from liminal.connection import BenchlingConnection

CURRENT_REVISION_ID = "{revision_id}"
"""
    with open(ENV_FILE_PATH, "w") as file:
        file.write(env_file)
    print(
        f"[bold green]Initialized Liminal CLI. Init revision file generated at {new_revision_file_path}"
    )


@app.command(
    name="generate-files",
    help="Generates the dropdown and entity schema files from your Benchling tenant and writes to the given path.",
)
def generate_files(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
    write_path: Path = typer.Option(
        Path("."),
        "-p",
        "--write-path",
        help="The path to write the generated files to.",
    ),
) -> None:
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    benchling_service = BenchlingService(benchling_connection, use_internal_api=True)
    if not write_path.exists():
        write_path.mkdir()
        print(f"[green]Created directory: {write_path}")
    generate_all_files(benchling_service, Path(write_path))


@app.command(
    name="current",
    help="Returns the CURRENT_REVISION_ID that your Benchling tenant is on. Reads from liminal/env.py.",
)
def current(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
) -> None:
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    print(
        f"[blue]{benchling_connection.current_revision_id_var_name}: {current_revision_id}[/blue]"
    )


@app.command(
    name="autogenerate",
    help="Generates a revision file with a list of operations to bring the given Benchling tenant up to date with the locally defined schemas. Writes revision file to liminal/versions/.",
)
def autogenerate(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
    description: str = typer.Argument(
        ...,
        help="A description of the revision being generated. This will also be included in the file name.",
    ),
) -> None:
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    benchling_service = BenchlingService(benchling_connection, use_internal_api=True)
    autogenerate_revision_file(
        benchling_service, VERSIONS_DIR_PATH, description, current_revision_id
    )


@app.command(
    name="upgrade",
    help="Upgrades the Benchling tenant by running revision file(s) based on the CURRENT_REVISION_ID and the passed in parameters. Runs the upgrade operations of each revision file in order.",
    context_settings={"ignore_unknown_options": True},
)
def upgrade(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
    upgrade_descriptor: str = typer.Argument(
        ...,
        help="Determines the revision files that get run. Pass in the 'revision_id' to upgrade to that revision. Pass in 'head' to upgrade to the latest revision. Pass in '+n' to make a relative revision based on the current revision id.",
    ),
) -> None:
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    benchling_service = BenchlingService(benchling_connection, use_internal_api=True)
    upgrade_revision_id = upgrade_benchling_tenant(
        benchling_service, VERSIONS_DIR_PATH, current_revision_id, upgrade_descriptor
    )
    update_env_revision_id(ENV_FILE_PATH, benchling_tenant, upgrade_revision_id)
    print(
        f"[dim]Set {benchling_tenant}_CURRENT_REVISION_ID to {upgrade_revision_id} in liminal/env.py"
    )
    print("[bold green]Migration complete")


@app.command(
    name="downgrade",
    help="Downgrades the Benchling tenant by running revision file(s) based on the CURRENT_REVISION_ID and the passed in parameters. Runs the downgrade operations of each revision file in order.",
    context_settings={"ignore_unknown_options": True},
)
def downgrade(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
    downgrade_descriptor: str = typer.Argument(
        ...,
        help="Determines the revision files that get run. Pass in the 'revision_id' to downgrade to that revision. Pass in '-n' to make a relative revision based on the current revision id.",
    ),
) -> None:
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    benchling_service = BenchlingService(benchling_connection, use_internal_api=True)
    downgrade_revision_id = downgrade_benchling_tenant(
        benchling_service, VERSIONS_DIR_PATH, current_revision_id, downgrade_descriptor
    )
    update_env_revision_id(ENV_FILE_PATH, benchling_tenant, downgrade_revision_id)
    print(
        f"[dim]Set {benchling_tenant}_CURRENT_REVISION_ID to {downgrade_revision_id} in liminal/env.py"
    )
    print("[bold green]Migration complete")


@app.command(
    name="live-test",
    hidden=True,
    help="Kicks off a live test migration to check that the CLI and operations are working.",
)
def live_test(
    benchling_tenant: str = typer.Argument(
        ..., help="Benchling tenant (or alias) to connect to."
    ),
    test_entity_schema_migration: bool = typer.Option(
        False,
        "-es",
        "--entity-schema-migration",
        help="Run the entity schema migration.",
    ),
    test_dropdown_migration: bool = typer.Option(
        False, "-d", "--dropdown-migration", help="Run the dropdown migration."
    ),
    execute: bool = typer.Option(
        False, "-e", "--execute", help="Execute the migration operations"
    ),
) -> None:
    if test_entity_schema_migration and test_dropdown_migration:
        raise ValueError(
            "Only one of --entity-schema-migration or --dropdown-migration can be set."
        )
    current_revision_id, benchling_connection = read_local_liminal_dir(
        LIMINAL_DIR_PATH, benchling_tenant
    )
    benchling_service = BenchlingService(benchling_connection, use_internal_api=True)
    if test_entity_schema_migration:
        mock_entity_schema_full_migration(
            benchling_service, "test_dont_touch", dry_run=not execute
        )
    if test_dropdown_migration:
        mock_dropdown_full_migration(
            benchling_service, "test_dont_touch", dry_run=not execute
        )


print("Starting Liminal CLI...")
app()
