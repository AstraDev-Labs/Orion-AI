"""Data source connectors for Deep Research."""

from orion.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from orion.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import orion.connectors.obsidian  # noqa: F401

try:
    import orion.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import orion.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import orion.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import orion.connectors.news_rss  # noqa: F401
except ImportError:
    pass
