"""Exception hierarchy for the JARVIS agent.

Every layer raises a subclass of :class:`JarvisError` so the state machine can
route failures into ERROR -> RECOVERING without swallowing unexpected bugs.
"""


class JarvisError(Exception):
    """Base class for all recoverable agent errors."""


class ConfigurationError(JarvisError):
    """Bad or missing configuration (env vars, paths, model names)."""


class ModuleUnavailableError(JarvisError):
    """A hardware/library dependency is absent (e.g. no display, no browser)."""


class InvalidTransitionError(JarvisError):
    """An illegal state-machine transition was attempted."""


class PerceptionError(JarvisError):
    """The data-ingestion engine failed to fetch/parse its target."""


class ReasoningError(JarvisError):
    """The cognitive pipeline returned malformed or unusable output."""


class ActionError(JarvisError):
    """An automation trigger (GUI/browser) failed at runtime."""


class VerificationError(JarvisError):
    """Post-action verification could not confirm the desired outcome."""


class SkillNotFoundError(JarvisError):
    """Requested skill is not registered with the agent."""
