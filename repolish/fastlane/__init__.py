"""Fast lanes: per-provider CLIs for quick, scoped apply runs.

A fast lane is a named slice of a provider's work, declared via
:meth:`~repolish.providers.models.Provider.create_fast_lanes` as
``{lane_name: FastLaneSpec}``. The hook is no-arg on purpose: nothing it
returns can depend on peer-provider context, so a lane's file set is
identical whether it runs alone or merged into a full ``repolish apply``.

This package exposes only what other parts of the system use:

- :func:`merge_fast_lanes` / :func:`restrict_to_lane`: the bundle transforms
  the apply pipeline calls (full runs merge every lane's contributions;
  lane runs restrict the bundle to exactly one lane).
- :func:`provider_cli`: the CLI factory providers ship as their
  ``<name>-cli`` console script.
"""

from repolish.fastlane.cli import provider_cli
from repolish.fastlane.transforms import merge_fast_lanes, restrict_to_lane

__all__ = ['merge_fast_lanes', 'provider_cli', 'restrict_to_lane']
