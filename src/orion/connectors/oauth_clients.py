"""OAuth clients that ship with Orion, so users can just click "Sign in".

Without a shipped client every user has to create their own Google Cloud
project and OAuth client before signing in -- the step people found too hard.
With one, the Connections screen shows a single "Sign in with Google" button.

This is safe to publish. Google treats a *Desktop app* OAuth client as a public
client: its "secret" is not confidential by design (it ships inside every
installed app). Protection comes from PKCE and the loopback redirect, which
``orion.connectors.oauth`` uses for every sign-in -- the tokens a user gets are
stored only on their own machine and never pass through the Orion project.

To enable it (project maintainer, once):

1. console.cloud.google.com -> create a project -> APIs & Services -> enable the
   Google Calendar, People (contacts) and Tasks APIs.
2. OAuth consent screen -> External -> app name "Orion", support email, and the
   scopes in ``GOOGLE_ONE_CLICK_SCOPES`` below. Publish the app.
3. Credentials -> Create credentials -> OAuth client ID -> Desktop app.
4. Paste the client ID and secret below (or set ORION_GOOGLE_CLIENT_ID /
   ORION_GOOGLE_CLIENT_SECRET at build time).

Until Google verifies the app, users see an "unverified app" notice they can
click through, and sign-ins are capped at 100 users. The scopes below are
"sensitive", not "restricted": verification is a free review. Drive and Gmail
scopes are "restricted" (paid security assessment), so they are left to
users who bring their own client -- email already works through the Email
connection's app password instead.
"""

from __future__ import annotations

import os

GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""

GOOGLE_ONE_CLICK_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
)


def google_client() -> tuple[str, str]:
    """The shipped Google client, or ("", "") when none is configured."""
    client_id = os.environ.get("ORION_GOOGLE_CLIENT_ID", "").strip() or GOOGLE_CLIENT_ID
    secret = os.environ.get("ORION_GOOGLE_CLIENT_SECRET", "").strip() or GOOGLE_CLIENT_SECRET
    return (client_id, secret) if client_id and secret else ("", "")


__all__ = ["GOOGLE_ONE_CLICK_SCOPES", "google_client"]
