"""Testing utilities for the Repolish CLI.

Provides a :class:`CliRunner` that mirrors the interface of
``typer.testing.CliRunner`` so that existing tests need no changes once the
CLI is migrated to Cyclopts.
"""

import io
import sys
from dataclasses import dataclass, field

import cyclopts
from rich.console import Console


@dataclass
class Result:
    """Outcome of a :meth:`CliRunner.invoke` call."""

    exit_code: int
    output: str
    exception: BaseException | None = field(default=None)


class CliRunner:
    """Minimal test runner for Cyclopts :class:`~cyclopts.App` instances.

    Usage mirrors ``typer.testing.CliRunner``::

        from repolish.cli.testing import CliRunner
        from repolish.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ['apply', '--check'])
        assert result.exit_code == 0
        assert 'Usage' in result.output

    If the app has a registered ``@app.meta.default`` handler the runner calls
    ``app.meta(args)`` so that shared meta-parameters (e.g. ``--verbose``) are
    honoured.  Otherwise ``app(args)`` is used directly.

    Rich console output is captured via an in-memory :class:`~rich.console.Console`
    so that the ``result.output`` field contains the full text written to either
    *stdout* or *stderr* during the invocation.
    """

    def invoke(
        self,
        app: cyclopts.App,
        args: list[str] | tuple[str, ...] | None = None,
        *,
        catch_exceptions: bool = True,
    ) -> Result:
        """Invoke *app* with *args* and return a :class:`Result`.

        Args:
            app: The Cyclopts application to invoke.
            args: CLI arguments to pass (equivalent to ``sys.argv[1:]``).
            catch_exceptions: When ``False`` any exception other than
                :class:`SystemExit` propagates out of this call (useful for
                ``pytest.raises`` assertions).

        Returns:
            A :class:`Result` with *exit_code*, *output*, and optionally
            *exception* populated.
        """
        if args is None:
            args = []

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, soft_wrap=True)
        orig_stdout = sys.stdout
        orig_console = app.console
        orig_error_console = app.error_console

        exit_code = 0
        exception: BaseException | None = None

        try:
            sys.stdout = buf
            app.console = console
            app.error_console = console

            use_meta = app.meta.default_command is not None
            if use_meta:
                app.meta(list(args))
            else:
                app(list(args))

        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 0
        except BaseException as exc:
            exception = exc
            exit_code = 1
            if not catch_exceptions:
                raise
        finally:
            sys.stdout = orig_stdout
            app.console = orig_console
            app.error_console = orig_error_console

        return Result(
            exit_code=exit_code,
            output=buf.getvalue(),
            exception=exception,
        )
