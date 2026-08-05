"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from orion.skills.sources.base import ResolvedSkill, SourceResolver
from orion.skills.sources.github import GitHubResolver
from orion.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from orion.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
