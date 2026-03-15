"""SimpleProvider - the class-based repolish provider for this test fixture.

Demonstrates the minimal provider contract:
- a typed Pydantic context (Ctx)
- an anchor that the deployed template consumes
"""

from pydantic import BaseModel

from repolish import BaseContext, Provider


class Ctx(BaseContext):
    """Context for the simple test provider."""

    greeting: str = 'hello from simple_provider'


class SimpleProvider(Provider[Ctx, BaseModel]):
    """Minimal installed provider used by the integration test suite."""

    def create_anchors(self, context: Ctx) -> dict[str, str]:
        """Return the greeting anchor consumed by README.simple-provider.md."""
        return {'simple-provider-greeting': context.greeting}
