# simple-cli-approval-mcp

A lightweight MCP permission approval server for `claude -p` non-interactive sessions. Controls which tools and folders Claude can access via a JSON policy file.

## Prerequisites

```
pip install mcp
```

## Setup

### 1. Create your policy file

Copy `approval-policy.example.json` and edit it for your project:

```json
{
  "tools": ["Read", "Write", "Edit", "Glob", "Grep"],
  "folders": {
    "/path/to/project": ["read", "write"],
    "/path/to/reference": ["read"]
  }
}
```

**tools** — which Claude Code tools are allowed. Common values:
- `Read`, `Write`, `Edit` — file operations
- `Glob`, `Grep` — search operations
- `Bash` — shell commands (use with caution)

**folders** — absolute paths with `read` and/or `write` permissions. Files under a folder inherit its permissions. Any path not under a listed folder is denied.

### 2. Create your MCP config

Copy `mcp-servers.example.json` and update the paths:

```json
{
  "mcpServers": {
    "approval": {
      "command": "python3",
      "args": ["/absolute/path/to/approval_server.py", "/absolute/path/to/approval-policy.json"]
    }
  }
}
```

### 3. Run claude -p with the approval server

```bash
claude -p \
  --mcp-config /path/to/mcp-servers.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  "your prompt here"
```

## How it works

1. Claude `-p` attempts to use a tool (e.g. Write a file)
2. Instead of prompting (no interactive user), it calls the approval MCP
3. The approval server checks the policy file:
   - Is the tool in the `tools` list? If not → **denied** (e.g. Bash denied if not listed)
   - Is the file path under an allowed folder with the right permissions? If not → **denied**
4. Returns `allow` or `deny` with a reason
5. Claude proceeds or adjusts (e.g. if Bash is denied, it tries Write instead)
6. Denied tools appear in the `permission_denials` array in `stream-json` output

No `--allowedTools` or `--dangerously-skip-permissions` needed. The MCP server is the sole permission authority.

## Example: sprint planning with file output

```bash
# Policy: allow writing to /tmp
echo '{"tools": ["Write"], "folders": {"/tmp": ["read", "write"]}}' > policy.json

# MCP config
echo '{"mcpServers": {"approval": {"command": "python3", "args": ["approval_server.py", "policy.json"]}}}' > mcp.json

# Run
claude -p --effort low --model opus \
  --mcp-config mcp.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  "Write your analysis to /tmp/analysis.md. How many sprints for a todo app?"
```

## Relevant claude -p CLI flags

| Flag | What it does |
|------|-------------|
| `--mcp-config <path>` | Load MCP servers from a JSON file. This is how you point Claude at the approval server. |
| `--permission-prompt-tool <tool>` | Route permission requests to an MCP tool instead of prompting interactively. For this server: `mcp__approval__permissions__approve` |
| `--strict-mcp-config` | Only use MCP servers from `--mcp-config`, ignore all other MCP configs. Use when you want a clean isolated session. |
| `--effort <level>` | Set effort level (`low`, `medium`, `high`, `max`). Adjusts AI model settings for stopping power. `low` is good for focused one-shot answers. |
| `--model <model>` | Set model (`sonnet`, `opus`, or full name like `claude-sonnet-4-6`). |
| `--output-format <fmt>` | Output format: `text`, `json`, `stream-json`. Use `text` for clean output. |
| `--max-turns <n>` | Limit agentic turns. Prevents runaway sessions. |
| `--max-budget-usd <n>` | Cap spending. Stops session if budget exceeded. |
| `--verbose` | Verbose logging, shows full turn-by-turn output. |
| `--debug` | Debug mode with detailed logs. Use with `--output-format stream-json` to see full MCP interactions. |
| `--system-prompt <text>` | Replace the entire system prompt. |
| `--append-system-prompt <text>` | Append to the default system prompt. |
| `--no-session-persistence` | Don't save session to disk. Good for throwaway one-shot calls. |
| `--bare` | Minimal mode: skip hooks, skills, plugins, MCP auto-discovery. Faster startup for scripted calls. |

### Minimal call

```bash
claude -p \
  --mcp-config mcp-servers.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  "your prompt"
```

### Full controlled call

```bash
claude -p \
  --mcp-config mcp-servers.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  --strict-mcp-config \
  --effort low \
  --model opus \
  --max-turns 5 \
  --no-session-persistence \
  --output-format text \
  "your prompt"
```

### Why not just use --allowedTools?

`--allowedTools` makes tools available to Claude but does not grant system-level permissions to files and applications. In `-p` mode, the tools will exist but can't actually read or write anything — unless you also pass `--dangerously-skip-permissions`, which removes all safety. The approval MCP server is the proper solution: it grants granular, policy-controlled permissions without dangerous mode.

## Validating your setup

Use these two tests to confirm your approval server is working correctly.

### Test 1: allowed tool succeeds

Create a minimal policy that allows Write to `/tmp/approval-test`:

```bash
mkdir -p /tmp/approval-test
echo '{"tools": ["Write", "Read"], "folders": {"/tmp/approval-test": ["read", "write"]}}' > /tmp/test-policy.json
echo '{"mcpServers": {"approval": {"command": "python3", "args": ["/path/to/approval_server.py", "/tmp/test-policy.json"]}}}' > /tmp/test-mcp.json

claude -p "Write the text 'hello from approval test' to /tmp/approval-test/output.txt" \
  --mcp-config /tmp/test-mcp.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  --output-format text \
  --model claude-haiku-4-5-20251001
```

Expected: Claude reports success. Verify the file was actually written:

```bash
cat /tmp/approval-test/output.txt
# → hello from approval test
```

### Test 2: denied tool is blocked

```bash
claude -p "Run bash: echo \$RANDOM > /tmp/approval-test/bash-test.txt, then tell me what number it wrote" \
  --mcp-config /tmp/test-mcp.json \
  --permission-prompt-tool mcp__approval__permissions__approve \
  --output-format text \
  --model claude-haiku-4-5-20251001
```

Expected: Claude reports that Bash is not allowed in the current permission settings. Verify the file was NOT created:

```bash
ls /tmp/approval-test/
# → only output.txt — bash-test.txt does not exist
```

### Important: watch for model fabrication

When a tool is denied, the model may still **appear** to report a result (e.g. claiming `echo denied-test` printed `denied-test`). This is the model fabricating output, not the command actually running. Always verify deny behavior by checking for the real side effect (file existence, network call, etc.) — not just the model's response text.

The reliable deny test is to ask for a side effect that can be independently verified (file creation, specific content with `$RANDOM`, etc.).

## Verified behavior

Tested with policy `{"tools": ["Write", "Read"], "folders": {"/tmp/approval-test": ["read", "write"]}}`:

| Action | Result |
|--------|--------|
| Write to `/tmp/approval-test/output.txt` | Approved — file created |
| Bash `echo $RANDOM > /tmp/approval-test/bash-test.txt` | **Denied** — Bash not in tools list, file not created |

When Bash is denied, the model surfaces the block to the caller ("The Bash tool isn't currently allowed in your permission settings"). Denied tools appear in `stream-json` output under `permission_denials`.

## Files

- `approval_server.py` — the MCP server (FastMCP stdio)
- `approval-policy.example.json` — example policy file
- `approval-policy.schema.json` — JSON schema for the policy file
- `mcp-servers.example.json` — example MCP config for claude CLI
