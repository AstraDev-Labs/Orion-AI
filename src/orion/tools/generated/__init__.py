"""Tools the AI has written and the user has explicitly approved.

Every file here was proposed via propose_new_tool (tool_forge.py), passed
static AST validation and an isolated smoke test, and was only written to
disk after a real human "yes" to the queued create_tool action -- see
proactive_tools.py's _exec_create_tool. Nothing writes here automatically.
"""
