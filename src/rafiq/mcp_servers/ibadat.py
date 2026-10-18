"""
Ibadat MCP server - prayer_times, qibla, hijri, council_resolutions
"""

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    args = parser.parse_args()
    if args.http:
        import uvicorn
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok", "server": "ibadat"}

        @app.post("/tools/{tool_name}")
        def call_tool(tool_name: str, payload: dict):
            from rafiq.mcp_servers.toolbus import call_tool as _call

            if tool_name not in [
                "prayer_times",
                "qibla",
                "hijri_from_gregorian",
                "council_resolutions",
            ]:
                return {"error": "tool not found"}
            try:
                result = _call(tool_name, **payload)
                return {"result": result}
            except Exception as e:
                return {"error": str(e)}

        uvicorn.run(app, host="0.0.0.0", port=8002)
    else:
        try:
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("ibadat")

            @mcp.tool()
            def prayer_times(location: str = "عرفة"):
                from rafiq.mcp_servers.toolbus import prayer_times_tool

                return prayer_times_tool(location)

            @mcp.tool()
            def qibla(lat: float = 21.35, lon: float = 39.98):
                from rafiq.mcp_servers.toolbus import qibla_tool

                return qibla_tool(lat, lon)

            @mcp.tool()
            def hijri_from_gregorian(date: str = None):
                from rafiq.mcp_servers.toolbus import hijri_tool

                return hijri_tool(date)

            @mcp.tool()
            def council_resolutions(topic: str = None):
                from rafiq.mcp_servers.toolbus import council_resolutions_tool

                return council_resolutions_tool(topic)

            mcp.run()
        except ImportError:
            pass
