import sys
import uuid
import random
import os
from fastmcp import FastMCP
from typing import List, Dict, Any, Optional, Tuple, Set
from db_repository import (
    DynamoRepository,
    setup_dynamodb_table,
    DYNAMO_TABLE_NAME
)

# Default values
DEFAULT_MAX_COURTS = 3
DEFAULT_PAIRING_MODE = "BALANCED"

class TournamentService:
    """
    Handles all the business logic for a single tournament.
    """
    
    def __init__(self, repo: DynamoRepository, pk_value: str, tournament_id: str):
        self.repo = repo
        self.pk = pk_value
        self.tournament_id = tournament_id


    def get_config_value(self, key: str, default: Any) -> Any:
        config = self.repo.get_config()
        return config.get(key, default)

    def get_max_courts(self) -> int:
        return int(self.get_config_value('max_courts', DEFAULT_MAX_COURTS))

    def set_max_courts(self, total_courts: int) -> str:
        if total_courts < 0:
            return "Error: Total courts must be 0 or greater."
        if self.repo.update_config("SET max_courts = :c", {':c': total_courts}):
            return f"Success: Court capacity set to {total_courts}."
        return "Error: Failed to set court capacity."

    def get_current_round(self) -> int:
        return int(self.get_config_value('current_round', 1))

    def set_current_round(self, round_number: int) -> str:
        if round_number < 1:
            return "Error: Round number must be 1 or greater."
        if self.repo.update_config("SET current_round = :r", {':r': round_number}):
            return f"Success: Current round set to {round_number}."
        return "Error: Failed to set round."

    def get_pairing_mode(self) -> str:
        return self.get_config_value('pairing_mode', DEFAULT_PAIRING_MODE)

    def set_pairing_mode(self, mode: str) -> str:
        mode = mode.upper()
        if mode not in ["RANDOM", "BALANCED"]:
            return "Error: Mode must be 'RANDOM' or 'BALANCED'."
        if self.repo.update_config("SET pairing_mode = :m", {':m': mode}):
            return f"Success: Pairing mode set to {mode}."
        return "Error: Failed to set pairing mode."

    # Player & Match Logic

    def get_players(self) -> List[Dict[str, Any]]:
        players = self.repo.get_players()
        players.sort(key=lambda p: (p.get('score', 0), p.get('wins', 0)), reverse=True)
        return players

    def get_matches(self, status: str) -> List[Dict[str, Any]]:
        all_matches = self.repo.get_matches()
        all_matches.sort(key=lambda m: (m.get('round_number', 999), m.get('SK', '')))
        return [m for m in all_matches if m.get('status') == status]

    def _get_available_players(self) -> List[Dict[str, Any]]:
        all_players = self.get_players()
        active_matches = self.get_matches("ACTIVE")
        pending_matches = self.get_matches("PENDING")
        busy_player_ids = set()

        for match in active_matches + pending_matches:
            players_in_match = [
                match.get('tA_p1_id'), match.get('tA_p2_id'),
                match.get('tB_p1_id'), match.get('tB_p2_id')
            ]
            for pid in players_in_match:
                if pid:
                    busy_player_ids.add(pid)
        return [p for p in all_players if p['player_id'] not in busy_player_ids]

    def _get_rematch_fingerprints(self) -> Set[frozenset]:
        fingerprints = set()
        completed_matches = self.get_matches("COMPLETED")
        for m in completed_matches:
            p_ids = frozenset([
                m.get('tA_p1_id'), m.get('tA_p2_id'),
                m.get('tB_p1_id'), m.get('tB_p2_id')
            ])
            if None not in p_ids:
                fingerprints.add(p_ids)
        return fingerprints

    # core Tournament Logic

    def add_player(self, name: str, level: int) -> str:
        if not 1 <= level <= 5:
            return "Error: Level must be between 1 and 5."
        player_id = str(uuid.uuid4())
        item = {
            'PK': self.pk,
            'SK': f"PLAYER#{player_id}",
            'player_id': player_id,
            'name': name,
            'level': level,
            'wins': 0,
            'losses': 0,
            'score': 0,
        }
        if self.repo.put_item(item):
            return f"Player '{name}' (Level {level}) added with ID {player_id}."
        return "Error: Failed to add player."

    def _create_random_foursomes(self, players: List[Dict]) -> List[Tuple]:
        random.shuffle(players)
        return [tuple(players[i:i+4]) for i in range(0, len(players) - 3, 4)]

    def _create_balanced_foursomes(self, players: List[Dict]) -> List[Tuple]:
        players.sort(key=lambda p: p.get('level', 3), reverse=True)
        teams = []
        l, r = 0, len(players) - 1
        while l < r:
            teams.append((players[l], players[r]))
            l += 1
            r -= 1
        random.shuffle(teams)
        return [(teams[i][0], teams[i][1], teams[i+1][0], teams[i+1][1])
                for i in range(0, len(teams) - 1, 2)]

    def create_doubles_matches(self) -> str:
        pairing_mode = self.get_pairing_mode()
        players = self._get_available_players()

        if len(players) < 4:
            return "Error: Not enough available players for a doubles match (need 4)."

        bye_player_names = []
        if len(players) % 4 != 0:
            num_byes = len(players) % 4
            players.sort(key=lambda p: p.get('level', 3))
            for _ in range(num_byes):
                bye_player_names.append(players.pop(0)['name'])

        if pairing_mode == "RANDOM":
            foursomes = self._create_random_foursomes(players)
        else:
            foursomes = self._create_balanced_foursomes(players)

        current_round = self.get_current_round()
        played_matchups = self._get_rematch_fingerprints()
        new_matches_info = []
        warnings = []

        for (tA_p1, tA_p2, tB_p1, tB_p2) in foursomes:
            match_id = str(uuid.uuid4())
            fingerprint = frozenset([
                tA_p1['player_id'], tA_p2['player_id'],
                tB_p1['player_id'], tB_p2['player_id']
            ])
            is_rematch = (fingerprint in played_matchups)
            item = {
                'PK': self.pk, 'SK': f"MATCH#{match_id}",
                'match_id': match_id, 'match_type': "DOUBLES",
                'status': "PENDING", 'round_number': current_round,
                'is_rematch': is_rematch,
                'tA_p1_id': tA_p1['player_id'], 'tA_p1_name': tA_p1['name'],
                'tA_p2_id': tA_p2['player_id'], 'tA_p2_name': tA_p2['name'],
                'tB_p1_id': tB_p1['player_id'], 'tB_p1_name': tB_p1['name'],
                'tB_p2_id': tB_p2['player_id'], 'tB_p2_name': tB_p2['name'],
            }
            self.repo.put_item(item)
            match_name = f"(D) {tA_p1['name']}/{tA_p2['name']} vs {tB_p1['name']}/{tB_p2['name']}"
            match_info = f"{match_name} (ID: {match_id}) - Round {current_round}"
            if is_rematch:
                match_info += " (WARNING: REMATCH)"
                warnings.append(match_name)
            new_matches_info.append(match_info)

        response = f"Created {len(new_matches_info)} matches ({pairing_mode} mode):\n" + "\n".join(new_matches_info)
        if warnings:
            response += f"\n\n⚠️ {len(warnings)} match(es) are rematches."
        if bye_player_names:
            response += f"\nPlayers with bye: {', '.join(bye_player_names)}"
        return response

    def start_match(self, match_id: str) -> str:
        max_courts = self.get_max_courts()
        active_matches = self.get_matches(status="ACTIVE")
        if len(active_matches) >= max_courts:
            return f"Error: All {max_courts} courts are full."

        match_item = self.repo.get_match(match_id)
        if not match_item:
            return f"Error: Match ID {match_id} not found."
        if match_item.get('status') != "PENDING":
            return f"Error: Match not in PENDING state."

        key = {'PK': self.pk, 'SK': f"MATCH#{match_id}"}
        if self.repo.update_item(key, "SET #st = :s", {"#st": "status"}, {':s': "ACTIVE"}):
            return f"Match started: {self._get_match_name(match_item)}"
        return "Error: Could not start match."

    def report_score(self, match_id: str, teamA_score: int, teamB_score: int) -> str:
        match_item = self.repo.get_match(match_id)
        if not match_item:
            return f"Error: Match ID {match_id} not found."
        if match_item.get('status') == "COMPLETED":
            return "Error: Match already scored."

        if teamA_score > teamB_score:
            win_score, lose_score, is_draw = 3, 0, False
        elif teamB_score > teamA_score:
            win_score, lose_score, is_draw = 0, 3, False
        else:
            win_score, lose_score, is_draw = 1, 1, True

        players_update = []
        teamA = [match_item['tA_p1_id'], match_item['tA_p2_id']]
        teamB = [match_item['tB_p1_id'], match_item['tB_p2_id']]
        for pid in teamA:
            players_update.append((pid, win_score, lose_score))
        for pid in teamB:
            players_update.append((pid, lose_score, win_score))

        match_key = {'PK': self.pk, 'SK': f"MATCH#{match_id}"}
        match_vals = {':s': "COMPLETED", ':sA': teamA_score, ':sB': teamB_score}
        self.repo.update_item(match_key, "SET #st = :s, teamA_score = :sA, teamB_score = :sB",
                              {'#st': 'status'}, match_vals)

        for pid, w, l in players_update:
            self.repo.update_item({'PK': self.pk, 'SK': f"PLAYER#{pid}"},
                                  "ADD wins :w, losses :l, score :s",
                                  None, {':w': int(w > l), ':l': int(l > w), ':s': w})

        match_name = self._get_match_name(match_item)
        if is_draw:
            return f"Draw reported: {match_name} ({teamA_score}-{teamB_score})"
        winner = "Team A" if teamA_score > teamB_score else "Team B"
        return f"{winner} wins: {match_name} ({teamA_score}-{teamB_score})"

    def _get_match_name(self, match_item: Dict[str, Any]) -> str:
        return (f"(D) {match_item['tA_p1_name']}/{match_item['tA_p2_name']} vs "
                f"{match_item['tB_p1_name']}/{match_item['tB_p2_name']}")

    def get_standings_string(self) -> str:
        players = self.get_players()
        active = self.get_matches("ACTIVE")
        pending = self.get_matches("PENDING")
        max_courts = self.get_max_courts()
        current_round = self.get_current_round()
        mode = self.get_pairing_mode()

        lines = [
            f"Tournament: {self.tournament_id}",
            f"Courts in use: {len(active)}/{max_courts}",
            f"Current Round: {current_round}",
            f"Pairing Mode: {mode}\n",
            "## Player Standings",
        ]
        if not players:
            lines.append("No players yet.")
        else:
            lines.append("Rank | Name (Lvl) | Score | W-L")
            lines.append("---- | ----------- | ------ | ----")
            for i, p in enumerate(players, 1):
                lines.append(f"{i} | {p['name']} (L{p['level']}) | {p['score']} | {p['wins']}-{p['losses']}")

        lines.append("\n## Active Matches")
        if not active:
            lines.append("None")
        else:
            for m in active:
                lines.append(f"- {self._get_match_name(m)} (R{m['round_number']})")

        lines.append("\n## Pending Matches")
        if not pending:
            lines.append("None")
        else:
            for m in pending:
                lines.append(f"- {self._get_match_name(m)} (R{m['round_number']})")
        return "\n".join(lines)



setup_dynamodb_table(DYNAMO_TABLE_NAME)

mcp = FastMCP(
    instructions=(
        "A server to manage recreational doubles tournaments. "
        "You can create multiple tournaments, each with its own players, matches, and configuration."
    )
)

def get_service(tournament_id: str) -> TournamentService:
    pk_value = f"TOURNAMENT#{tournament_id}"
    repo = DynamoRepository(table_name=DYNAMO_TABLE_NAME, pk_value=pk_value)
    return TournamentService(repo, pk_value, tournament_id)


# Tools

@mcp.tool()
def create_tournament(tournament_name: Optional[str] = None, total_courts: int = 3):
    """
    Creates a new tournament and initializes its config.
    """
    tournament_id = f"T_{uuid.uuid4().hex[:8].upper()}"
    pk_value = f"TOURNAMENT#{tournament_id}"
    repo = DynamoRepository(DYNAMO_TABLE_NAME, pk_value)

    config_item = {
        'PK': pk_value,
        'SK': 'CONFIG',
        'tournament_name': tournament_name or f"Tournament {tournament_id}",
        'max_courts': total_courts,
        'current_round': 1,
        'pairing_mode': 'BALANCED',
    }
    repo.put_item(config_item)
    return f"Tournament created: {tournament_id} with {total_courts} courts."


@mcp.tool()
def add_player_to_tournament(tournament_id: str, name: str, level: int):
    service = get_service(tournament_id)
    return service.add_player(name, level)

@mcp.tool()
def set_court_capacity(tournament_id: str, total_courts: int):
    service = get_service(tournament_id)
    return service.set_max_courts(total_courts)

@mcp.tool()
def set_current_round(tournament_id: str, round_number: int):
    service = get_service(tournament_id)
    return service.set_current_round(round_number)

@mcp.tool()
def set_pairing_mode(tournament_id: str, mode: str):
    service = get_service(tournament_id)
    return service.set_pairing_mode(mode)

@mcp.tool()
def create_doubles_matches(tournament_id: str):
    service = get_service(tournament_id)
    return service.create_doubles_matches()

@mcp.tool()
def start_match_on_court(tournament_id: str, match_id: str):
    service = get_service(tournament_id)
    return service.start_match(match_id)

@mcp.tool()
def report_match_score(tournament_id: str, match_id: str, teamA_score: int, teamB_score: int):
    service = get_service(tournament_id)
    return service.report_score(match_id, teamA_score, teamB_score)

@mcp.tool()
def get_standings(tournament_id: str):
    service = get_service(tournament_id)
    return service.get_standings_string()


if __name__ == "__main__":
    print("MCP Server Running (Multi-Tournament Mode)", file=sys.stderr)
    mcp.run(transport='stdio')