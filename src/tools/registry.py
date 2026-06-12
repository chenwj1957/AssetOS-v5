from __future__ import annotations

from src.tools.artifact_tools import ARTIFACT_TOOLS
from src.tools.calc_tool import CALC_TOOLS
from src.tools.fact_tools import FACT_TOOLS
from src.tools.base import ToolSpec
from src.tools.memory_tools import MEMORY_TOOLS
from src.tools.research_tools import RESEARCH_TOOLS


def list_tools() -> list[ToolSpec]:
    return [*MEMORY_TOOLS, *FACT_TOOLS, *CALC_TOOLS, *RESEARCH_TOOLS, *ARTIFACT_TOOLS]


def get_tool(name: str) -> ToolSpec:
    tools = {tool.name: tool for tool in list_tools()}
    if name not in tools:
        raise KeyError(f"Unknown tool '{name}'. Available: {sorted(tools)}")
    return tools[name]
