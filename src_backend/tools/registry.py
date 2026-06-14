from __future__ import annotations

from src_backend.tools.artifact_tools import ARTIFACT_TOOLS
from src_backend.tools.calc_tool import CALC_TOOLS
from src_backend.tools.fact_tools import FACT_TOOLS
from src_backend.tools.base import ToolSpec
from src_backend.tools.memory_tools import MEMORY_TOOLS
from src_backend.tools.research_tools import RESEARCH_TOOLS


def list_tools() -> list[ToolSpec]:
    return [*MEMORY_TOOLS, *FACT_TOOLS, *CALC_TOOLS, *RESEARCH_TOOLS, *ARTIFACT_TOOLS]
