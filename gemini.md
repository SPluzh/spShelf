# Project Instructions

## Maya Development
When writing code for Autodesk Maya (Python/MEL), you **MUST** first consult the documentation.
Use the available **MCP tools** (`maya-docs` server) to look up commands and API classes:

1.  **For standard commands (`maya.cmds`):**
    Use `get_maya_command_help(command_name='...')`.

2.  **For OpenMaya API (`maya.api.OpenMaya`):**
    Use `search_maya_docs_url(query='...')` or check cached docs.

**Rule:** Do not guess flags or method names. Always verify against the documentation provided by the MCP tools before generating code.
