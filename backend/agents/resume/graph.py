"""招聘简历审查图：原文提取、结构化、六维并行评审、诊断和总结。"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from backend.agents.resume.nodes import (
    extract_text_node, extract_structured_node, run_six_dimensions_node,
    diagnose_issues_node, generate_summary_node,
)
from backend.agents.resume.state import ResumeState


@lru_cache(maxsize=1)
def build_resume_graph():
    graph = StateGraph(ResumeState)
    graph.add_node("extract_text", extract_text_node)
    graph.add_node("extract_structured", extract_structured_node)
    graph.add_node("run_six_dimensions", run_six_dimensions_node)
    graph.add_node("diagnose_issues", diagnose_issues_node)
    graph.add_node("generate_summary", generate_summary_node)
    graph.add_edge(START, "extract_text")
    graph.add_edge("extract_text", "extract_structured")
    graph.add_edge("extract_structured", "run_six_dimensions")
    graph.add_edge("run_six_dimensions", "diagnose_issues")
    graph.add_edge("diagnose_issues", "generate_summary")
    graph.add_edge("generate_summary", END)
    return graph.compile()
