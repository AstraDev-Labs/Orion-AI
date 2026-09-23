"""Direct, connection-aware Notion actions for the chat agent."""

from __future__ import annotations

from typing import Any

from orion.connectors.notion import (
    NotionConnector,
    _extract_page_title,
    _notion_api_create_page,
    _notion_api_get_blocks,
    _notion_api_get_page,
    _notion_api_search,
    _render_blocks_to_markdown,
)
from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


def _token() -> str:
    token = NotionConnector()._resolve_token()
    if not token:
        raise RuntimeError(
            "Notion is not configured. Add its integration secret in Connections."
        )
    return token


@ToolRegistry.register("notion_search_pages")
class NotionSearchPagesTool(BaseTool):
    """Search pages the user's Notion integration can access."""

    tool_id = "notion_search_pages"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Search the connected Notion workspace for pages by title or content. "
                "Use this for requests about pages in Notion; do not open a browser instead. "
                "Returns page IDs, titles, and URLs. The integration only sees pages shared with it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words to find in Notion pages.",
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(
                tool_name=self.tool_id,
                content="Enter a search phrase for Notion.",
                success=False,
            )
        try:
            data = _notion_api_search(
                _token(), query=query, page_size=params.get("max_results", 10)
            )
            pages = data.get("results", [])
            rows = []
            for page in pages:
                if page.get("object") != "page":
                    continue
                rows.append(
                    {
                        "id": page.get("id", ""),
                        "title": _extract_page_title(page),
                        "url": page.get("url", ""),
                    }
                )
            if not rows:
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"No accessible Notion pages matched '{query}'. Share pages with the Orion integration if you expect them to appear.",
                    success=True,
                    metadata={"results": []},
                )
            content = "\n".join(
                f"{row['title']} (id: {row['id']})\n{row['url']}" for row in rows
            )
            return ToolResult(
                tool_name=self.tool_id,
                content=content,
                success=True,
                metadata={"results": rows},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Notion search failed: {exc}",
                success=False,
            )


@ToolRegistry.register("notion_get_page")
class NotionGetPageTool(BaseTool):
    """Read a shared Notion page and its text content."""

    tool_id = "notion_get_page"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read a Notion page the connected integration can access. Use a page ID returned by notion_search_pages.",
            parameters={
                "type": "object",
                "properties": {"page_id": {"type": "string"}},
                "required": ["page_id"],
            },
            category="knowledge",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        page_id = str(params.get("page_id", "")).strip()
        if not page_id:
            return ToolResult(
                tool_name=self.tool_id,
                content="A Notion page ID is required.",
                success=False,
            )
        try:
            token = _token()
            page = _notion_api_get_page(token, page_id)
            blocks = _notion_api_get_blocks(token, page_id)
            body = _render_blocks_to_markdown(blocks)
            return ToolResult(
                tool_name=self.tool_id,
                content=f"{_extract_page_title(page)}\n{page.get('url', '')}\n\n{body}",
                success=True,
                metadata={"page_id": page_id, "url": page.get("url", "")},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Could not read the Notion page: {exc}",
                success=False,
            )


@ToolRegistry.register("notion_create_page")
class NotionCreatePageTool(BaseTool):
    """Create a child page under an explicitly shared Notion page and verify it."""

    tool_id = "notion_create_page"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Create a new page in the connected Notion workspace under a shared parent page. "
                "For 'save this to Notion', first search for a suitable parent if its ID is unknown, "
                "then create the page and confirm the returned API readback. Never open notion.so as a substitute."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "New page title."},
                    "content": {"type": "string", "description": "Page text content."},
                    "parent_page_id": {
                        "type": "string",
                        "description": "ID of a page shared with the integration; find it with notion_search_pages.",
                    },
                },
                "required": ["title", "content", "parent_page_id"],
            },
            category="knowledge",
            required_capabilities=["network:fetch"],
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title", "")).strip()
        content = str(params.get("content", ""))
        parent_id = str(params.get("parent_page_id", "")).strip()
        if not title or not content.strip() or not parent_id:
            return ToolResult(
                tool_name=self.tool_id,
                content="A title, non-empty content, and parent_page_id are required. Search Notion for a shared parent page first.",
                success=False,
            )
        if len(content) > 50_000:
            return ToolResult(
                tool_name=self.tool_id,
                content="This note is too long for one Notion page action (50,000 character limit). Split it into smaller pages.",
                success=False,
            )
        try:
            token = _token()
            created = _notion_api_create_page(
                token, parent_page_id=parent_id, title=title, content=content
            )
            page_id = str(created.get("id", ""))
            if not page_id:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="Notion accepted the request but returned no page ID, so creation could not be verified.",
                    success=False,
                )
            # Read the page and its children back from Notion before reporting success.
            page = _notion_api_get_page(token, page_id)
            blocks = _notion_api_get_blocks(token, page_id)
            readback = "".join(
                part.get("plain_text", "")
                for block in blocks
                for part in block.get(block.get("type", ""), {}).get("rich_text", [])
            )
            verified_title = _extract_page_title(page) == title
            verified_content = readback == content
            verified = verified_title and verified_content
            page_url = str(page.get("url") or created.get("url") or "")
            if not verified:
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"Notion created page {page_id}, but readback did not match the submitted title/content. I cannot confirm the save. {page_url}",
                    success=False,
                    metadata={
                        "page_id": page_id,
                        "url": page_url,
                        "created": True,
                        "verified": False,
                    },
                )
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Created and verified Notion page '{title}'.\n{page_url}",
                success=True,
                metadata={
                    "page_id": page_id,
                    "url": page_url,
                    "created": True,
                    "verified": True,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Notion page creation or readback failed: {exc}. No browser fallback was attempted.",
                success=False,
            )


__all__ = ["NotionCreatePageTool", "NotionGetPageTool", "NotionSearchPagesTool"]
