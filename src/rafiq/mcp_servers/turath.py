"""
Turath MCP server - FastMCP
Exposes: search_passages, get_passage, get_ayah_ref, get_hadith_record
"""

import argparse


def create_app():
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("turath")

        @mcp.tool()
        def search_passages(query: str, madhhab: str = None, limit: int = 5):
            from rafiq.mcp_servers.toolbus import search_passages_tool

            res = search_passages_tool(query, madhhab, limit)
            if isinstance(res, dict):
                # flatten dict
                flat = []
                for lst in res.values():
                    flat.extend([p.model_dump() if hasattr(p, "model_dump") else p for p in lst])
                return flat
            return [p.model_dump() if hasattr(p, "model_dump") else str(p) for p in res]

        @mcp.tool()
        def get_passage(passage_id: str, madhhab: str):
            from rafiq.mcp_servers.toolbus import get_passage_tool

            p = get_passage_tool(passage_id, madhhab)
            return p.model_dump() if p and hasattr(p, "model_dump") else None

        @mcp.tool()
        def get_ayah_ref(sura: int, ayah: int):
            from rafiq.mcp_servers.toolbus import get_ayah_ref as _ayah

            return _ayah(sura, ayah)

        @mcp.tool()
        def get_hadith_record(collection: str, number: str):
            from rafiq.mcp_servers.toolbus import get_hadith_record as _had

            return _had(collection, number)

        return mcp
    except ImportError:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    args = parser.parse_args()
    if args.http:
        # Run as FastAPI for http mode
        import uvicorn
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok", "server": "turath"}

        @app.post("/tools/{tool_name}")
        def call_tool(tool_name: str, payload: dict):
            from rafiq.mcp_servers.toolbus import call_tool as _call

            if tool_name not in [
                "search_passages",
                "get_passage",
                "get_ayah_ref",
                "get_hadith_record",
            ]:
                return {"error": "tool not found"}
            try:
                result = _call(tool_name, **payload)
                return {"result": result}
            except Exception as e:
                return {"error": str(e)}

        uvicorn.run(app, host="0.0.0.0", port=8001)
    else:
        mcp = create_app()
        if mcp:
            mcp.run()
