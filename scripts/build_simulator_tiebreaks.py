from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TREE_DIR = ROOT / "tree"
CACHE_PATH = ROOT / "simulator-tiebreaks.json"
DEFAULT_SERVER_URL = "http://127.0.0.1:50000"
DEFAULT_SERVER_SCRIPT = (
    Path.home() / "Documents" / "NAGAAnki" / "NAGA" / "start_mahjong_cpp_server.ps1"
)
PROJECT_VERSION = "0.9.1"
SIMULATOR_TAIL = "123p56s33z"
CURRENT_TURN = 9
ROUND_WIND = 0
SEAT_WIND = 1
EV_EPSILON = 1e-9

TILE_NAMES = (
    [f"{rank}m" for rank in range(1, 10)]
    + [f"{rank}p" for rank in range(1, 10)]
    + [f"{rank}s" for rank in range(1, 10)]
    + [f"{rank}z" for rank in range(1, 8)]
)
TILE_CODE_TO_INDEX = {code: index for index, code in enumerate(TILE_NAMES)}
TENHOU_TILE_INDEX_TO_CODE = {
    **{10 + rank: f"{rank}m" for rank in range(1, 10)},
    **{20 + rank: f"{rank}p" for rank in range(1, 10)},
    **{30 + rank: f"{rank}s" for rank in range(1, 10)},
    **{40 + rank: f"{rank}z" for rank in range(1, 8)},
}


def first_match(pattern: str) -> Path:
    matches = sorted(TREE_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no file matched: {TREE_DIR / pattern}")
    return matches[0]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_change(text: str) -> tuple[str, str]:
    tiles = re.findall(r"[1-9]m", text)
    if len(tiles) != 2:
        raise ValueError(f"unsupported change text: {text}")
    return tiles[0], tiles[1]


def extract_tile_codes(text: str) -> list[str]:
    digits: list[str] = []
    result: list[str] = []
    for char in text:
        if char.isdigit():
            digits.append(char)
            continue
        if char not in "mpsz":
            raise ValueError(f"unsupported suit: {char}")
        result.extend(f"{digit}{char}" for digit in digits)
        digits = []
    if digits:
        raise ValueError(f"missing suit after digits: {''.join(digits)}")
    return result


def normalize_response_tile(tile: Any) -> str:
    if isinstance(tile, str):
        stripped = tile.strip()
        if len(stripped) == 2 and stripped[0].isdigit() and stripped[1] in "mpsz":
            return stripped
        if stripped.isdigit():
            tile = int(stripped)
        else:
            raise RuntimeError(f"unsupported tile code: {tile}")
    if isinstance(tile, int):
        if 0 <= tile < len(TILE_NAMES):
            return TILE_NAMES[tile]
        if tile in TENHOU_TILE_INDEX_TO_CODE:
            return TENHOU_TILE_INDEX_TO_CODE[tile]
    raise RuntimeError(f"unsupported tile id: {tile}")


def build_payload(hand: str) -> dict[str, Any]:
    hand_indices = [TILE_CODE_TO_INDEX[code] for code in extract_tile_codes(hand)]
    return {
        "enable_reddora": False,
        "enable_uradora": False,
        "enable_shanten_down": True,
        "enable_tegawari": True,
        "enable_riichi": False,
        "round_wind": ROUND_WIND,
        "dora_indicators": [],
        "hand": hand_indices,
        "hand_tiles": hand_indices,
        "melds": [],
        "seat_wind": SEAT_WIND,
        "version": PROJECT_VERSION,
        "current_turn": CURRENT_TURN,
    }


def post_json(server_url: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    request = urllib.request.Request(
        server_url.rstrip("/") + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"mahjong-cpp request failed: {exc}") from exc
    if not isinstance(data, dict) or not data.get("success"):
        raise RuntimeError(str(data.get("err_msg") or "mahjong-cpp request failed"))
    return data


def safe_index(values: list[Any], index: int, default: float = 0.0) -> float:
    if 0 <= index < len(values):
        return float(values[index])
    return default


def parse_candidates(response_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    response = response_data.get("response") or {}
    shanten = response.get("shanten") or {}
    candidates: dict[str, dict[str, Any]] = {}
    for stat in response.get("stats") or []:
        try:
            discard = normalize_response_tile(stat["tile"])
        except Exception:
            continue
        candidates[discard] = {
            "discard": discard,
            "shanten": int(stat.get("shanten", shanten.get("all", 99))),
            "expectedScore": safe_index(stat.get("exp_score") or [], CURRENT_TURN),
            "winProbability": safe_index(stat.get("win_prob") or [], CURRENT_TURN),
            "tenpaiProbability": safe_index(stat.get("tenpai_prob") or [], CURRENT_TURN),
        }
    return candidates


def is_port_open(server_url: str, timeout_sec: float = 0.5) -> bool:
    parsed = urllib.parse.urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def ensure_server(server_url: str, server_script: Path, startup_timeout: float) -> None:
    if is_port_open(server_url):
        return
    if not server_script.exists():
        raise RuntimeError(f"mahjong-cpp start script not found: {server_script}")
    port = urllib.parse.urlparse(server_url).port or 50000
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(server_script),
            str(port),
        ],
        cwd=str(server_script.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.time() + startup_timeout
    while time.time() < deadline:
        if is_port_open(server_url):
            return
        time.sleep(0.3)
    raise RuntimeError(f"mahjong-cpp server did not become ready: {server_url}")


def resulting_shape(source_shape: str, draw: str, discard: str) -> str:
    tiles = [f"{digit}m" for digit in source_shape.removesuffix("m")]
    tiles.append(draw)
    tiles.remove(discard)
    return "".join(sorted(tile[0] for tile in tiles)) + "m"


def find_tie_groups() -> list[dict[str, Any]]:
    node_rows = read_csv(first_match("*_nodes.csv"))
    edge_rows = read_csv(first_match("*_directed_edges.csv"))
    nodes_by_shape = {row["shape"]: row for row in node_rows}
    edge_changes: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in edge_rows:
        draw, discard = parse_change(row["change"])
        edge_changes.setdefault((row["from"], draw), []).append(
            {"discard": discard, "toShape": row["to"]}
        )

    groups: list[dict[str, Any]] = []
    for (source_shape, draw), existing in sorted(edge_changes.items()):
        target_ukeire = max(
            int(nodes_by_shape[item["toShape"]]["ukeire_count"]) for item in existing
        )
        seven_tiles = [f"{digit}m" for digit in source_shape.removesuffix("m")] + [draw]
        alternatives: list[dict[str, Any]] = []
        for discard in sorted(set(seven_tiles)):
            destination = resulting_shape(source_shape, draw, discard)
            destination_row = nodes_by_shape.get(destination)
            if not destination_row:
                continue
            if int(destination_row["ukeire_count"]) != target_ukeire:
                continue
            alternatives.append(
                {
                    "discard": discard,
                    "toShape": destination,
                    "toUkeireCount": target_ukeire,
                }
            )
        if len(alternatives) <= 1:
            continue
        groups.append(
            {
                "key": f"{source_shape}|{draw}",
                "sourceShape": source_shape,
                "draw": draw,
                "hand": source_shape.removesuffix("m") + draw[0] + "m" + SIMULATOR_TAIL,
                "alternatives": alternatives,
            }
        )
    return groups


def simulate_group(
    group: dict[str, Any],
    server_url: str,
    timeout_sec: float,
) -> tuple[str, dict[str, Any]]:
    response = post_json(server_url, build_payload(group["hand"]), timeout_sec)
    candidates_by_discard = parse_candidates(response)
    candidates = []
    for alternative in group["alternatives"]:
        candidate = candidates_by_discard.get(alternative["discard"])
        if candidate is None:
            raise RuntimeError(
                f"{group['key']}: discard missing from simulator: {alternative['discard']}"
            )
        candidates.append({**alternative, **candidate})
    best_score = max(candidate["expectedScore"] for candidate in candidates)
    best_discards = sorted(
        candidate["discard"]
        for candidate in candidates
        if abs(candidate["expectedScore"] - best_score) <= EV_EPSILON
    )
    for candidate in candidates:
        candidate["differenceFromBest"] = candidate["expectedScore"] - best_score
        candidate["isBest"] = candidate["discard"] in best_discards
    return group["key"], {
        "sourceShape": group["sourceShape"],
        "draw": group["draw"],
        "hand": group["hand"],
        "settings": {
            "tail": SIMULATOR_TAIL,
            "currentTurn": CURRENT_TURN,
            "roundWind": "east",
            "seatWind": "south",
            "doraIndicators": [],
        },
        "bestDiscards": best_discards,
        "bestExpectedScore": best_score,
        "candidates": sorted(candidates, key=lambda item: item["discard"]),
    }


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return dict(data.get("groups") or {})


def write_cache(groups: dict[str, Any]) -> None:
    payload = {
        "version": 1,
        "settings": {
            "tail": SIMULATOR_TAIL,
            "currentTurn": CURRENT_TURN,
            "roundWind": "east",
            "seatWind": "south",
            "doraIndicators": [],
        },
        "groups": dict(sorted(groups.items())),
    }
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--server-script", type=Path, default=DEFAULT_SERVER_SCRIPT)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    ensure_server(args.server_url, args.server_script, args.startup_timeout)
    tie_groups = find_tie_groups()
    cache = {} if args.force else load_cache()
    pending = [group for group in tie_groups if args.force or group["key"] not in cache]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"tie groups={len(tie_groups)} cached={len(cache)} pending={len(pending)}")

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(simulate_group, group, args.server_url, args.timeout): group
            for group in pending
        }
        for future in as_completed(futures):
            key, result = future.result()
            cache[key] = result
            completed += 1
            if completed % 25 == 0 or completed == len(pending):
                write_cache(cache)
                print(f"completed={completed}/{len(pending)}")

    write_cache(cache)
    print(f"wrote {CACHE_PATH.relative_to(ROOT)}: {len(cache)} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
