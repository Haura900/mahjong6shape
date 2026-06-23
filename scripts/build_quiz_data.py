from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREE_DIR = ROOT / "tree"
OUTPUT = ROOT / "quiz-data.json"
JS_OUTPUT = ROOT / "quiz-data.js"
SIMULATOR_TIEBREAK_PATH = ROOT / "simulator-tiebreaks.json"

NAMED_SHAPE_NAMES = {
    "階段型",
    "ピアノ＋α型",
    "エントツリャンメン",
    "エントツシャンポン",
    "シャンポンリャンメン",
    "エントツカンチャン",
    "リャンメンシャンポン・2121型",
    "リャンメンシャンポン・2211型",
    "リャンメンカンチャン",
    "中ぶくれカンチャン",
    "とび階段",
    "離れシャンポン",
    "イーペーリャンカン",
    "カンチャンシャンポン",
    "離れリャンカン",
}


def first_match(pattern: str) -> Path:
    matches = sorted(TREE_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no file matched: {TREE_DIR / pattern}")
    return matches[0]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_tiles(text: str) -> list[str]:
    return [part for part in text.split() if part]


def parse_change(text: str) -> tuple[str, str]:
    match = re.fullmatch(r"ツモ(.+?) / 打(.+)", text.strip())
    if not match:
        raise ValueError(f"unsupported change text: {text}")
    return match.group(1), match.group(2)


def shape_tiles(shape: str) -> list[str]:
    digits = [char for char in shape if char.isdigit()]
    return [f"{digit}m" for digit in digits] + ["3z", "3z"]


def shape_weight(shape: str) -> int:
    digits = [int(char) for char in shape if char.isdigit()]
    counts = {rank: digits.count(rank) for rank in range(1, 10)}
    weight = 1
    for rank, count in counts.items():
        if count > 4:
            raise ValueError(f"{shape}: {rank}m appears {count} times")
        weight *= math.comb(4, count)
    return weight


def resulting_shape(source_shape: str, draw: str, discard: str) -> str:
    tiles = [f"{digit}m" for digit in source_shape.removesuffix("m")]
    tiles.append(draw)
    tiles.remove(discard)
    return "".join(sorted(tile[0] for tile in tiles)) + "m"


def change_record(
    source_row: dict[str, str],
    destination_row: dict[str, str],
    draw: str,
    discard: str,
) -> dict[str, object]:
    return {
        "draw": draw,
        "discard": discard,
        "toShape": destination_row["shape"],
        "toHand": destination_row["shape"] + "33z",
        "toShapeName": destination_row["shape_name"],
        "fromUkeireCount": int(source_row["ukeire_count"]),
        "toUkeireCount": int(destination_row["ukeire_count"]),
        "fromFixedRyanmenCount": int(source_row["fixed_ryanmen_count"]),
        "toFixedRyanmenCount": int(destination_row["fixed_ryanmen_count"]),
        "isNamedShape": destination_row["shape_name"] in NAMED_SHAPE_NAMES,
    }


def load_simulator_tiebreaks() -> dict[str, dict[str, object]]:
    if not SIMULATOR_TIEBREAK_PATH.exists():
        return {}
    payload = json.loads(SIMULATOR_TIEBREAK_PATH.read_text(encoding="utf-8"))
    return dict(payload.get("groups") or {})


def attach_simulator_comparison(
    changes: list[dict[str, object]],
    source_shape: str,
    simulator_tiebreaks: dict[str, dict[str, object]],
) -> None:
    by_draw: dict[str, list[dict[str, object]]] = {}
    for change in changes:
        by_draw.setdefault(str(change["draw"]), []).append(change)
    for draw, draw_changes in by_draw.items():
        if len(draw_changes) <= 1:
            continue
        comparison = simulator_tiebreaks.get(f"{source_shape}|{draw}")
        if not comparison:
            continue
        candidates = {
            str(candidate["discard"]): candidate
            for candidate in comparison.get("candidates") or []
        }
        best_discards = set(comparison.get("bestDiscards") or [])
        for change in draw_changes:
            discard = str(change["discard"])
            candidate = candidates.get(discard)
            if not candidate:
                continue
            change["simulatorPreferred"] = discard in best_discards
            change["simulatorExpectedScore"] = float(candidate["expectedScore"])
            change["simulatorDifferenceFromBest"] = float(candidate["differenceFromBest"])
            change["simulatorComparison"] = comparison


def attach_furiten_risks(
    changes_by_shape: dict[str, list[dict[str, object]]],
    nodes_by_shape: dict[str, dict[str, str]],
) -> None:
    for changes in changes_by_shape.values():
        for change in changes:
            discarded_tile = str(change["discard"])
            destination = str(change["toShape"])
            risks: list[dict[str, object]] = []
            for next_change in changes_by_shape.get(destination, []):
                if not bool(next_change.get("isNamedShape")):
                    continue
                next_destination = str(next_change["toShape"])
                waits = parse_tiles(nodes_by_shape[next_destination]["ukeire_tiles"])
                if discarded_tile not in waits:
                    continue
                risks.append(
                    {
                        "draw": next_change["draw"],
                        "discard": next_change["discard"],
                        "toShape": next_destination,
                        "toShapeName": next_change["toShapeName"],
                        "waits": waits,
                        "furitenTile": discarded_tile,
                    }
                )
            change["furitenRisk"] = bool(risks)
            if risks:
                change["furitenRiskDetails"] = risks


def main() -> int:
    nodes_path = first_match("*_nodes.csv")
    edges_path = first_match("*_directed_edges.csv")
    node_rows = read_csv(nodes_path)
    edge_rows = read_csv(edges_path)
    nodes_by_shape = {row["shape"]: row for row in node_rows}
    simulator_tiebreaks = load_simulator_tiebreaks()

    changes_by_shape: dict[str, list[dict[str, object]]] = {shape: [] for shape in nodes_by_shape}
    for row in edge_rows:
        src = row["from"]
        dst = row["to"]
        draw, discard = parse_change(row["change"])
        changes_by_shape[src].append(
            change_record(nodes_by_shape[src], nodes_by_shape[dst], draw, discard)
        )

    for source_shape, changes in changes_by_shape.items():
        source_row = nodes_by_shape[source_shape]
        by_draw: dict[str, list[dict[str, object]]] = {}
        for change in changes:
            by_draw.setdefault(str(change["draw"]), []).append(change)
        for draw, draw_changes in by_draw.items():
            target_ukeire = max(int(change["toUkeireCount"]) for change in draw_changes)
            seven_tiles = [f"{digit}m" for digit in source_shape.removesuffix("m")] + [draw]
            existing = {
                (str(change["discard"]), str(change["toShape"]))
                for change in draw_changes
            }
            for discard in sorted(set(seven_tiles)):
                destination = resulting_shape(source_shape, draw, discard)
                destination_row = nodes_by_shape.get(destination)
                if not destination_row:
                    continue
                if int(destination_row["ukeire_count"]) != target_ukeire:
                    continue
                if (discard, destination) in existing:
                    continue
                changes.append(
                    change_record(source_row, destination_row, draw, discard)
                )
        attach_simulator_comparison(changes, source_shape, simulator_tiebreaks)

    attach_furiten_risks(changes_by_shape, nodes_by_shape)

    problems = []
    for row in node_rows:
        shape = row["shape"]
        changes = sorted(
            changes_by_shape[shape],
            key=lambda item: (str(item["draw"]), str(item["discard"]), str(item["toShape"])),
        )
        problems.append(
            {
                "shape": shape,
                "hand": row["hand"],
                "shapeName": row["shape_name"],
                "isNamedShape": row["shape_name"] in NAMED_SHAPE_NAMES,
                "handTiles": shape_tiles(shape),
                "ukeireTiles": parse_tiles(row["ukeire_tiles"]),
                "ukeireCount": int(row["ukeire_count"]),
                "ukeireTypeCount": int(row["ukeire_type_count"]),
                "fixedRyanmenCount": int(row["fixed_ryanmen_count"]),
                "distanceToFinal": int(row["distance_to_final"]),
                "weight": shape_weight(shape),
                "changes": changes,
            }
        )

    payload = {
        "version": 1,
        "source": {
            "nodes": nodes_path.relative_to(ROOT).as_posix(),
            "edges": edges_path.relative_to(ROOT).as_posix(),
        },
        "namedShapeNames": sorted(NAMED_SHAPE_NAMES),
        "tileCandidates": [f"{rank}m" for rank in range(1, 10)] + ["3z"],
        "problems": problems,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    JS_OUTPUT.write_text(
        "window.SIX_SHAPE_QUIZ_DATA="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(problems)} problems")
    print(f"wrote {JS_OUTPUT.relative_to(ROOT)}: {len(problems)} problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
