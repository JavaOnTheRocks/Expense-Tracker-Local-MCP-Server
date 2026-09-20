#Skeleton of the MCP Server side code
import random
from fastmcp import FastMCP

#create an fastmcp server instance/object
mcp=FastMCP(name="Demo server")

@mcp.tool
def add_numbers(a:float, b:float)-> float:
    """Add Two numbers togather."""
    return a+b

if __name__=="__main__":
    mcp.run()