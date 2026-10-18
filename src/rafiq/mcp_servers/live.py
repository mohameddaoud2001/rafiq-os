"""
Live MCP server - weather, fleet_status, truck_temps, well_sensors
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
            return {"status": "ok", "server": "live"}

        @app.post("/tools/{tool_name}")
        def call_tool(tool_name: str, payload: dict):
            from rafiq.mcp_servers.toolbus import call_tool as _call

            if tool_name not in ["weather", "fleet_status", "truck_temps", "well_sensors"]:
                return {"error": "tool not found"}
            try:
                result = _call(tool_name, **payload)
                return {"result": result}
            except Exception as e:
                return {"error": str(e)}

        uvicorn.run(app, host="0.0.0.0", port=8003)
    else:
        try:
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("live")

            @mcp.tool()
            def weather(location: str = "عرفة"):
                from rafiq.mcp_servers.toolbus import weather_tool

                return weather_tool(location)

            @mcp.tool()
            def fleet_status():
                from rafiq.mcp_servers.toolbus import fleet_status_tool

                return fleet_status_tool()

            @mcp.tool()
            def truck_temps():
                from rafiq.mcp_servers.toolbus import truck_temps_tool

                return truck_temps_tool()

            @mcp.tool()
            def well_sensors():
                from rafiq.mcp_servers.toolbus import well_sensors_tool

                return well_sensors_tool()

            mcp.run()
        except ImportError:
            pass
