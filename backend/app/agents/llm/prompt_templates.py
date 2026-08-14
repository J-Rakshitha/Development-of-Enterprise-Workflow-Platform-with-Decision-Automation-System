"""
Prompt Templates (LangChain)
==============================
Milestone 1 explicitly asks for "prompt templates" — this is LangChain's
`ChatPromptTemplate` abstraction, used here instead of building prompts as
raw Python f-strings. Centralizing them also means every agent's prompt
wording lives in one place, easy to review/tune independently of the
agent's decision logic.
"""
from langchain_core.prompts import ChatPromptTemplate

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_template(
    "An incident was detected on service '{service_name}'. "
    "Metrics: {raw_metrics}. Error signature: {error_signature}. "
    "This run was triggered by: {triggered_by}."
    "{memory_context}\n"
    "In 2 short sentences, explain the most likely root cause a DevOps engineer would suspect "
    "for THESE exact metrics. Do not copy prior memory verbatim. "
    "Do not invent specific commit hashes or filenames unless they appear in the metrics."
)

CONFLICT_RESOLUTION_PROMPT = ChatPromptTemplate.from_template(
    "Two developers, {dev_a_name} and {dev_b_name}, are both editing the function "
    "'{function_name}' in file '{file_path}' at the same time, which risks a merge conflict."
    "{memory_context}\n"
    "In 2 short sentences, suggest how they should coordinate to avoid losing each other's work."
)

CODE_REVIEW_PROMPT = ChatPromptTemplate.from_template(
    "Two developers, {dev_a_name} and {dev_b_name}, are editing '{function_name}' in "
    "'{file_path}' with a {risk_score}% merge-conflict risk."
    "{memory_context}\n"
    "In 2 short sentences, flag code-quality or style concerns they should address "
    "before merging (naming, tests, complexity)."
)

TOOL_SELECTION_PROMPT = ChatPromptTemplate.from_template(
    "You are selecting the single best tool to handle this situation.\n"
    "Situation: {situation}\n"
    "{memory_context}\n\n"
    "Available tools:\n{tool_descriptions}\n\n"
    "Reply with ONLY the exact tool name from the list above, nothing else."
)

SEMANTIC_ANALYSIS_PROMPT = ChatPromptTemplate.from_template(
    "Two developers, {dev_a_name} and {dev_b_name}, are editing '{function_name}' in "
    "'{file_path}' with {risk_score}% merge-conflict risk.\n"
    "AST diff report:\n{ast_report}\n"
    "Source snippet:\n{source_snippet}"
    "{memory_context}\n"
    "In 2-3 sentences, explain the semantic/logic-level conflict risk and what could break if both merge without coordination."
)

QUALITY_SCORECARD_PROMPT = ChatPromptTemplate.from_template(
    "Evaluate code quality for '{function_name}' in '{file_path}'.\n"
    "AST metrics:\n{metrics_json}\n"
    "Source:\n{source_snippet}\n"
    "In 2 short sentences, summarize quality concerns and one concrete improvement."
)

RESOLUTION_SYNTHESIZER_PROMPT = ChatPromptTemplate.from_template(
    "Conflict between {dev_a_name} and {dev_b_name} on '{function_name}' in '{file_path}'.\n"
    "Semantic risk: {semantic_risk}%, type: {conflict_type}, quality grade: {quality_grade}."
    "{memory_context}\n"
    "Suggest the best coordination strategy in 2 sentences (rebase, split work, or pair sync)."
)
