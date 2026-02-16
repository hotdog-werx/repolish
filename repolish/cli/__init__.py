"""CLI module for repolish.

This module provides the command-line interface for repolish. It follows a structured pattern
to keep the CLI layer thin and separate business logic from interface concerns.

Structure:
- `main.py`: The main Typer app. Defines the app, callback for backwards compatibility,
  and registers all subcommands.
- `apply.py`, `preview.py`, `link.py`: Individual command modules. Each defines a Typer
  command function that handles argument parsing and calls the corresponding business
  logic via `run_cli_command` for proper error handling.
- Business logic is in `repolish.commands.*`, keeping CLI focused on interface.

To add a new command:
1. Create a `command` function in `repolish/commands/new_command.py` with the core logic.
2. Create `repolish/cli/new_command.py` with a Typer command function that calls
   `run_cli_command(lambda: command(...))`.
3. Import the CLI function in `main.py` and register it with `app.command()(new_command_func)`.
4. Update any relevant exports or tests.

This separation ensures CLI commands are easy to test and maintain, with consistent error handling.
"""
