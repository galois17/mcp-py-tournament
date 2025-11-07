# Tournament MCP Server

This MCP Server exposes a Model Context Protocol (MCP) server for managing recreational tennis or pickleball tournaments.  
It provides deterministic, stateful control of tournaments — players, matches, rounds, and standings — while remaining conversational through an LLM like Gemini or ChatGPT.

---

## Why Not Just Let the LLM Handle It?

Modern LLMs can “pair players” or “keep score” in a chat, but that breaks down the moment you need consistency, persistence, or multi-user control.


---

## What the MCP Server Does

The server manages:
- Player registration with skill levels  
- Match generation (`BALANCED` or `RANDOM` pairing)  
- Court and round configuration  
- Score reporting and automatic leaderboard updates  
- Persistent records stored in DynamoDB  

Each tournament has a unique `tournament_id` and its own isolated state.

---

## Why MCP and not just let the LLM Prompt handle it?

| Concern | LLM-Only Approach | MCP-Backed Approach |
|----------|------------------|--------------------|
| Determinism | Pairings and results vary per run. | Uses defined algorithms (`BALANCED` / `RANDOM`) — always reproducible. |
| Record Keeping | State is lost once the chat ends. | All data persisted to DynamoDB. |
| Rules Enforcement | LLM might skip or misapply rules. | Strict validation logic in Python. |
| Multi-User Safety | Each chat has its own inconsistent memory. | Shared tournament state accessible via `tournament_id`. |
| Extensibility | Hard to add structure or APIs. | Easy to extend with new tools (e.g., `get_leaderboard_csv`, `get_player_stats`). |
| Auditing & Analytics | Impossible — no database. | Full historical data for analysis or dashboards. |

---

## Prerequisites

This MCP server requires access to **AWS DynamoDB** for storing tournament data.  
You must have:

1. An AWS account with DynamoDB permissions (`dynamodb:*` or equivalent).
2. Local AWS credentials configured via one of the following:
   - `~/.aws/credentials`
   - Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optionally `AWS_DEFAULT_REGION`)
   - IAM role if running on AWS infrastructure (Lambda, ECS, or EC2)
3. A DynamoDB table named `TournamentTable` (created automatically on first run if it doesn’t exist).

Example AWS CLI check:

```bash
aws dynamodb list-tables
```

---

## Extending This Server

Because it’s MCP-based, you can easily add new tools such as:

- `get_leaderboard_csv(tournament_id)` → exports results for Power BI or Excel  
- `get_player_stats(tournament_id, player_id)` → individual performance history  
- `simulate_round(tournament_id)` → run test tournaments automatically  

LLMs like Gemini can discover and call these tools dynamically.

---

## How It Works in Practice

1. **User:** “Let’s set up our tournament. We have 3 courts.”  
   → MCP creates a new tournament ID (`T_AB12CD34`) and stores base config.

2. **User:** “Add Sarah and Mike.”  
   → MCP saves players under that tournament’s partition.

3. **User:** “Create the first round of matches.”  
   → MCP runs `BALANCED` or `RANDOM` pairing algorithms — no duplicates.

4. **User:** “Report final score 21–17.”  
   → MCP updates standings, recalculates scores, and writes results back to DynamoDB.

5. **User:** “Show standings.”  
   → MCP retrieves deterministic state: who’s leading, active matches, etc

