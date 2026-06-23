"""1スート6枚形 + 西西 のイーシャンテンをグラフ化する。

Node:
    1-9の1スートから6枚を選び、西西を足した形のうち、受け入れを持つ形。

Undirected Edge:
    1枚を別の牌へ交換すると互いに変化可能なNode同士。

Directed Edge:
    無向Edgeで隣接する x, y について score(y) > score(x) なら x -> y。
    Edgeの意味は「悪い形から良い形への変化」。

推移簡約はしない。隣接していてscoreが上なら直接辺を残す。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
from dataclasses import dataclass, replace
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Callable, Iterable

try:
    from mahjong.shanten import Shanten
except ImportError as exc:
    raise SystemExit(
        "mahjong library is required. Install with: python -m pip install mahjong"
    ) from exc


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PREFIX = BASE_DIR / "6枚形変化木"
DEFAULT_VISUALIZER_OUTPUT = BASE_DIR / "6枚形変化木_visualizer.html"
PAI_IMAGE_DIR = Path(r"C:\Users\batam\Documents\NAGAAnki\NAGA\pai-images")
RANKS = tuple(range(1, 10))
WEST = 10
WEST_PAIR_TEXT = "33z"
SHANTEN_CONTEXT = "123p78s"
SHANTEN = Shanten()
NAMED_SHAPE_REPRESENTATIVES = {
    # https://mahjong.nekoeigo.net/fukugo-10/ 掲載形。
    # 平行移動・反転して一致する形はこの名前を優先する。
    "階段型": ("444556m",),
    "ピアノ＋α型": ("334567m", "344567m", "233456m"),
    "エントツリャンメン": ("344456m", "122234m"),
    "エントツシャンポン": ("444566m",),
    "シャンポンリャンメン": ("455566m",),
    "エントツカンチャン": ("244456m",),
    "リャンメンシャンポン・2121型": ("334556m",),
    "リャンメンシャンポン・2211型": ("334456m",),
    "リャンメンカンチャン": ("344568m",),
    "中ぶくれカンチャン": ("344457m",),
    "とび階段": ("444557m",),
    "離れシャンポン": ("334566m",),
    "イーペーリャンカン": ("133455m",),
    "カンチャンシャンポン": ("334568m",),
    "離れリャンカン": ("134568m",),
}


@dataclass(frozen=True)
class Node:
    shape: str
    counts: tuple[int, ...]
    shape_name: str
    ukeire_tiles: tuple[int, ...]
    ukeire_type_count: int
    ukeire_count: int
    improve_neighbor_count: int = 0
    max_neighbor_ukeire_count: int = 0
    avg_neighbor_ukeire_count: float = 0.0
    fixed_ryanmen_count: int = 0
    good_shape_score: int = 0
    score: tuple[float, ...] = ()


ScoreFunc = Callable[[Node], tuple[float, ...]]


def counts_to_shape(counts: tuple[int, ...]) -> str:
    return "".join(str(rank) * counts[rank - 1] for rank in RANKS) + "m"


def counts_to_tiles(counts: tuple[int, ...]) -> list[int]:
    return [rank for rank in RANKS for _ in range(counts[rank - 1])]


def tiles_to_counts(tiles: Iterable[int]) -> tuple[int, ...]:
    counts = [0] * 9
    for tile in tiles:
        counts[tile - 1] += 1
    return tuple(counts)


def canonical_equivalent_key(counts: tuple[int, ...]) -> str:
    """平行移動・反転で同じ6枚形を同一視するためのキー。"""

    tiles = counts_to_tiles(counts)
    candidates: list[str] = []
    for variant in (tiles, [10 - tile for tile in tiles]):
        shifted = sorted(tile - min(variant) + 1 for tile in variant)
        candidates.append("".join(map(str, shifted)))
    return min(candidates)


def shape_to_counts(shape: str) -> tuple[int, ...]:
    digits = [int(char) for char in shape if char.isdigit()]
    counts = [0] * 9
    for digit in digits:
        if not 1 <= digit <= 9:
            raise ValueError(f"rank out of range: {digit}")
        counts[digit - 1] += 1
        if counts[digit - 1] > 4:
            raise ValueError(f"{digit}m is more than 4")
    if sum(counts) != 6:
        raise ValueError(f"shape must have 6 tiles: {shape}")
    return tuple(counts)


def tile_index(code: str) -> int:
    rank = int(code[0])
    suit = code[1]
    base = {"m": 0, "p": 9, "s": 18, "z": 27}[suit]
    return base + rank - 1


def parse_mpsz(text: str) -> tuple[int, ...]:
    counts = [0] * 34
    digits: list[str] = []
    for char in text:
        if char.isdigit():
            digits.append(char)
            continue
        if char not in "mpsz":
            raise ValueError(f"unsupported suit: {char}")
        for digit in digits:
            counts[tile_index(digit + char)] += 1
        digits = []
    if digits:
        raise ValueError(f"missing suit after digits: {''.join(digits)}")
    return tuple(counts)


def tile_text(tile: int) -> str:
    if tile == WEST:
        return "3z"
    return f"{tile}m"


def tile_image_path(tile: int) -> Path:
    if tile == WEST:
        return PAI_IMAGE_DIR / "ji3-66-90-s.png"
    return PAI_IMAGE_DIR / f"man{tile}-66-90-s.png"


def hand_tiles(node: Node) -> list[int]:
    tiles = [
        rank
        for rank in RANKS
        for _ in range(node.counts[rank - 1])
    ]
    return tiles + [WEST, WEST]


def tile_img_html(tile: int, *, title: str = "") -> str:
    path = tile_image_path(tile)
    if not path.exists():
        return f'<span class="missing-tile">{html.escape(tile_text(tile))}</span>'
    label = html.escape(title or tile_text(tile), quote=True)
    return f'<img class="tile" src="{path.as_uri()}" alt="{label}" title="{label}">'


def hand_html(node: Node) -> str:
    return '<div class="tiles">' + "".join(tile_img_html(tile) for tile in hand_tiles(node)) + "</div>"


def ukeire_html(node: Node) -> str:
    parts = []
    for tile in node.ukeire_tiles:
        remaining = 2 if tile == WEST else 4 - node.counts[tile - 1]
        parts.append(
            f'<span class="ukeire">{tile_img_html(tile, title=f"{tile_text(tile)}({remaining})")}'
            f'<span class="count">x{remaining}</span></span>'
        )
    return '<div class="ukeire-list">' + "".join(parts) + "</div>"


def ukeire_text(node: Node) -> str:
    parts = []
    for tile in node.ukeire_tiles:
        remaining = 2 if tile == WEST else 4 - node.counts[tile - 1]
        parts.append(f"{tile_text(tile)}({remaining})")
    return " ".join(parts)


def generate_all_six_tile_counts() -> list[tuple[int, ...]]:
    result: list[tuple[int, ...]] = []
    for ranks in combinations_with_replacement(RANKS, 6):
        counts = [0] * 9
        for rank in ranks:
            counts[rank - 1] += 1
        if all(count <= 4 for count in counts):
            result.append(tuple(counts))
    return result


def remove_tile(counts: tuple[int, ...], rank: int) -> tuple[int, ...]:
    values = list(counts)
    values[rank - 1] -= 1
    return tuple(values)


def add_tile(counts: tuple[int, ...], rank: int) -> tuple[int, ...]:
    values = list(counts)
    values[rank - 1] += 1
    return tuple(values)


def shanten_counts_for_shape(counts6: tuple[int, ...]) -> list[int]:
    """6枚形+西西を13枚の通常手牌に埋め込み、mahjongで評価する。"""

    counts34 = list(parse_mpsz(SHANTEN_CONTEXT + WEST_PAIR_TEXT))
    for rank in RANKS:
        counts34[rank - 1] += counts6[rank - 1]
    return counts34


def library_shanten_for_shape(counts6: tuple[int, ...]) -> int:
    return SHANTEN.calculate_shanten(shanten_counts_for_shape(counts6))


def add_candidate_to_shanten_counts(counts34: list[int], tile: int) -> list[int]:
    values = counts34[:]
    index = 29 if tile == WEST else tile - 1
    values[index] += 1
    return values


def candidate_remaining(counts6: tuple[int, ...], tile: int) -> int:
    if tile == WEST:
        return 2
    return 4 - counts6[tile - 1]


def can_remove_sequence(counts: tuple[int, ...], start_rank: int) -> bool:
    return start_rank <= 7 and all(counts[start_rank - 1 + offset] > 0 for offset in range(3))


def remove_sequence(counts: tuple[int, ...], start_rank: int) -> tuple[int, ...]:
    values = list(counts)
    for offset in range(3):
        values[start_rank - 1 + offset] -= 1
    return tuple(values)


def can_remove_triplet(counts: tuple[int, ...], rank: int) -> bool:
    return counts[rank - 1] >= 3


def remove_triplet(counts: tuple[int, ...], rank: int) -> tuple[int, ...]:
    values = list(counts)
    values[rank - 1] -= 3
    return tuple(values)


def meld_removals(counts: tuple[int, ...]) -> Iterable[tuple[int, ...]]:
    for rank in RANKS:
        if can_remove_triplet(counts, rank):
            yield remove_triplet(counts, rank)
    for rank in range(1, 8):
        if can_remove_sequence(counts, rank):
            yield remove_sequence(counts, rank)


def can_form_melds(counts: tuple[int, ...], meld_count: int) -> bool:
    if meld_count == 0:
        return True
    for remaining in meld_removals(counts):
        if can_form_melds(remaining, meld_count - 1):
            return True
    return False


def is_ryanmen_taatsu(counts: tuple[int, ...]) -> bool:
    """残り2枚が両面ターツならTrue。12/89の辺張は除外する。"""

    if sum(counts) != 2:
        return False
    tiles = [rank for rank in RANKS for _ in range(counts[rank - 1])]
    return len(tiles) == 2 and tiles[1] == tiles[0] + 1 and 2 <= tiles[0] <= 7


def has_meld_pair_ryanmen(counts7: tuple[int, ...]) -> bool:
    """7枚から メンツ + 雀頭 + 両面ターツ を作れるか。"""

    if sum(counts7) != 7:
        return False
    for after_meld in meld_removals(counts7):
        for pair_rank in RANKS:
            if after_meld[pair_rank - 1] < 2:
                continue
            after_pair = list(after_meld)
            after_pair[pair_rank - 1] -= 2
            if is_ryanmen_taatsu(tuple(after_pair)):
                return True
    return False


def has_meld_and_ryanmen_taatsu(counts6: tuple[int, ...]) -> bool:
    """6枚形の中に、1メンツとリャンメン搭子を同時に含むならTrue。"""

    if sum(counts6) != 6:
        return False
    for after_meld in meld_removals(counts6):
        tiles = [rank for rank in RANKS for _ in range(after_meld[rank - 1])]
        for left, right in zip(tiles, tiles[1:]):
            if right == left + 1 and 2 <= left <= 7:
                return True
    return False


def has_two_melds(counts7: tuple[int, ...]) -> bool:
    """7枚の中に2メンツを含められるか。余り1枚は許容する。"""

    if sum(counts7) != 7:
        return False
    for discard_rank in RANKS:
        if counts7[discard_rank - 1] <= 0:
            continue
        remaining6 = remove_tile(counts7, discard_rank)
        if can_form_melds(remaining6, 2):
            return True
    return False


def is_after_draw_good(counts7: tuple[int, ...]) -> bool:
    """マンズを引いた時の 6枚形+西西 の受け入れ判定。

    西西をヘッドとして固定し、7枚化したマンズ部分に2メンツを含められるなら有効牌。
    """

    return has_two_melds(counts7)


def has_three_sided_wait_with_float(counts6: tuple[int, ...]) -> bool:
    """5連続形による三面張成分と、そこに絡まない不要牌を持つならTrue。"""

    if sum(counts6) != 6:
        return False
    for start in range(1, 6):
        run = set(range(start, start + 5))
        if not all(counts6[rank - 1] > 0 for rank in run):
            continue
        extra_tiles = [
            rank
            for rank in RANKS
            for _ in range(counts6[rank - 1] - (1 if rank in run else 0))
        ]
        if len(extra_tiles) == 1 and extra_tiles[0] not in run:
            return True
    return False


def taatsu_kind(left: int, right: int) -> str | None:
    if right == left + 1:
        if left == 1 or left == 8:
            return "ペンチャン"
        return "リャンメン"
    if right == left + 2:
        return "カンチャン"
    return None


def classify_three_tile_remainder(counts3: tuple[int, ...]) -> tuple[int, str] | None:
    tiles = counts_to_tiles(counts3)
    if len(tiles) != 3:
        return None

    pair_ranks = [rank for rank in RANKS if counts3[rank - 1] == 2]
    if pair_ranks:
        pair = pair_ranks[0]
        other = next(rank for rank in RANKS if rank != pair and counts3[rank - 1] > 0)
        kind = taatsu_kind(min(pair, other), max(pair, other))
        if kind == "リャンメン":
            return 90, "メンツ＋リャンメントイツ"
        if kind == "カンチャン":
            return 80, "メンツ＋カンチャントイツ"
        if kind == "ペンチャン":
            return 70, "メンツ＋ペンチャントイツ"
        return 30, "メンツ＋トイツ＋不要牌"

    unique_tiles = sorted(set(tiles))
    if len(unique_tiles) == 3:
        if unique_tiles[1] == unique_tiles[0] + 2 and unique_tiles[2] == unique_tiles[1] + 2:
            return 85, "メンツ＋リャンカン"
        for left, right in zip(unique_tiles, unique_tiles[1:]):
            if taatsu_kind(left, right):
                return 60, "メンツ＋ターツ＋不要牌"

    return 20, "メンツ＋不要牌2枚"


def classify_meld_based_shape(counts6: tuple[int, ...]) -> tuple[int, str] | None:
    candidates: list[tuple[int, str]] = []
    for remaining in meld_removals(counts6):
        classified = classify_three_tile_remainder(remaining)
        if classified:
            candidates.append(classified)
    return max(candidates, default=None)


def classify_non_meld_shape(counts6: tuple[int, ...]) -> str:
    pair_count = sum(1 for rank in RANKS if counts6[rank - 1] >= 2)
    triplet_count = sum(1 for rank in RANKS if counts6[rank - 1] >= 3)
    ryanmen_count = 0
    kanchan_count = 0
    penchan_count = 0
    for left in RANKS:
        for right in range(left + 1, 10):
            if counts6[left - 1] <= 0 or counts6[right - 1] <= 0:
                continue
            kind = taatsu_kind(left, right)
            if kind == "リャンメン":
                ryanmen_count += 1
            elif kind == "カンチャン":
                kanchan_count += 1
            elif kind == "ペンチャン":
                penchan_count += 1

    if pair_count >= 2 and ryanmen_count:
        return "リャンメンシャンポン系"
    if ryanmen_count and kanchan_count:
        return "リャンメンカンチャン系"
    if kanchan_count >= 2:
        return "リャンカン複合"
    if pair_count >= 2:
        return "トイツ複合形"
    if triplet_count:
        return "メンツ含み複合形"
    if ryanmen_count:
        return "リャンメン複合形"
    if kanchan_count:
        return "カンチャン複合形"
    if penchan_count:
        return "ペンチャン複合形"
    return "その他6枚形"


def named_shape_lookup(counts6: tuple[int, ...]) -> str | None:
    key = canonical_equivalent_key(counts6)
    for name, representatives in NAMED_SHAPE_REPRESENTATIVES.items():
        for representative in representatives:
            if key == canonical_equivalent_key(shape_to_counts(representative)):
                return name
    return None


def classify_shape_name(counts6: tuple[int, ...]) -> str:
    """6枚形の構造名を返す。サイト掲載の固有名は構造分類へ寄せる。"""

    named_shape = named_shape_lookup(counts6)
    if named_shape:
        return named_shape
    if has_three_sided_wait_with_float(counts6):
        return "三面張＋不要牌"
    meld_based = classify_meld_based_shape(counts6)
    if meld_based:
        _priority, name = meld_based
        return name
    return classify_non_meld_shape(counts6)


def effective_tiles(counts6: tuple[int, ...]) -> tuple[int, ...]:
    counts34 = shanten_counts_for_shape(counts6)
    base_shanten = SHANTEN.calculate_shanten(counts34)
    tiles: list[int] = []
    for tile in (*RANKS, WEST):
        if candidate_remaining(counts6, tile) <= 0:
            continue
        after_draw = add_candidate_to_shanten_counts(counts34, tile)
        if SHANTEN.calculate_shanten(after_draw) < base_shanten:
            tiles.append(tile)
    return tuple(tiles)


def build_base_nodes() -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    for counts in generate_all_six_tile_counts():
        if library_shanten_for_shape(counts) != 1:
            continue
        ukeire_tiles = effective_tiles(counts)
        if not ukeire_tiles:
            continue
        shape = counts_to_shape(counts)
        nodes[shape] = Node(
            shape=shape,
            counts=counts,
            shape_name=classify_shape_name(counts),
            ukeire_tiles=ukeire_tiles,
            ukeire_type_count=len(ukeire_tiles),
            ukeire_count=sum(candidate_remaining(counts, tile) for tile in ukeire_tiles),
            fixed_ryanmen_count=int(has_meld_and_ryanmen_taatsu(counts)),
        )
    return nodes


def build_undirected_edges(nodes: dict[str, Node]) -> dict[str, set[str]]:
    node_keys = set(nodes)
    edges: dict[str, set[str]] = {shape: set() for shape in nodes}

    for shape, node in nodes.items():
        tenpai_draws = set(node.ukeire_tiles)
        for src_rank in RANKS:
            if node.counts[src_rank - 1] <= 0:
                continue
            after_remove = remove_tile(node.counts, src_rank)
            for dst_rank in RANKS:
                if dst_rank == src_rank or after_remove[dst_rank - 1] >= 4:
                    continue
                # 受け入れ牌をツモった後に別牌を切る変化は、
                # すでにテンパイに取れるため「変化候補」から除外する。
                if dst_rank in tenpai_draws:
                    continue
                changed = add_tile(after_remove, dst_rank)
                neighbor_shape = counts_to_shape(changed)
                if neighbor_shape in node_keys:
                    edges[shape].add(neighbor_shape)
    return edges


def default_score(node: Node) -> tuple[float, ...]:
    return (
        node.ukeire_count,
        node.ukeire_type_count,
        node.improve_neighbor_count,
        node.max_neighbor_ukeire_count,
        node.avg_neighbor_ukeire_count,
    )


def dummy_score(node: Node) -> tuple[float, ...]:
    return (
        node.ukeire_count,
        node.ukeire_type_count,
        node.improve_neighbor_count,
        node.good_shape_score,
    )


def enrich_nodes(
    nodes: dict[str, Node],
    undirected_edges: dict[str, set[str]],
    score_func: ScoreFunc,
) -> dict[str, Node]:
    enriched: dict[str, Node] = {}
    for shape, node in nodes.items():
        neighbor_nodes = [nodes[neighbor] for neighbor in undirected_edges[shape]]
        neighbor_ukeire = [neighbor.ukeire_count for neighbor in neighbor_nodes]
        enriched[shape] = replace(
            node,
            improve_neighbor_count=sum(value > node.ukeire_count for value in neighbor_ukeire),
            max_neighbor_ukeire_count=max(neighbor_ukeire, default=0),
            avg_neighbor_ukeire_count=(
                sum(neighbor_ukeire) / len(neighbor_ukeire) if neighbor_ukeire else 0.0
            ),
        )

    return {
        shape: replace(node, score=score_func(node))
        for shape, node in enriched.items()
    }


def build_directed_edges(
    nodes: dict[str, Node],
    undirected_edges: dict[str, set[str]],
) -> list[tuple[str, str]]:
    directed: set[tuple[str, str]] = set()
    for x, neighbors in undirected_edges.items():
        candidates_by_draw: dict[int, list[str]] = {}
        no_draw_candidates: list[str] = []
        for y in neighbors:
            draw, _discard = transition_tiles(nodes[x], nodes[y])
            if draw is None:
                no_draw_candidates.append(y)
                continue
            candidates_by_draw.setdefault(draw, []).append(y)
        for candidates in [*candidates_by_draw.values(), no_draw_candidates]:
            improving = [
                y
                for y in candidates
                if (
                    nodes[y].ukeire_count > nodes[x].ukeire_count
                    or (
                        nodes[y].ukeire_count == nodes[x].ukeire_count
                        and nodes[y].fixed_ryanmen_count > nodes[x].fixed_ryanmen_count
                    )
                )
            ]
            if not improving:
                continue
            best_value = max(
                (nodes[y].ukeire_count, nodes[y].fixed_ryanmen_count, nodes[y].score)
                for y in improving
            )
            for y in improving:
                if (nodes[y].ukeire_count, nodes[y].fixed_ryanmen_count, nodes[y].score) == best_value:
                    directed.add((x, y))
    return sorted(directed, key=lambda edge: (edge[0], edge[1]))


def distance_to_final(
    nodes: dict[str, Node],
    directed_edges: list[tuple[str, str]],
) -> dict[str, int]:
    """各Nodeから最終形(sink)までの最長距離を返す。"""

    outgoing: dict[str, list[str]] = {shape: [] for shape in nodes}
    for src, dst in directed_edges:
        outgoing[src].append(dst)
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(shape: str) -> int:
        if shape in memo:
            return memo[shape]
        if shape in visiting:
            raise ValueError(f"cycle detected while calculating distance_to_final: {shape}")
        if not outgoing[shape]:
            memo[shape] = 0
            return 0
        visiting.add(shape)
        memo[shape] = 1 + min(visit(dst) for dst in outgoing[shape])
        visiting.remove(shape)
        return memo[shape]

    return {shape: visit(shape) for shape in nodes}


def transition_tiles(src: Node, dst: Node) -> tuple[int | None, int | None]:
    """srcからdstへの1枚交換を draw, discard として返す。"""

    draw: int | None = None
    discard: int | None = None
    for rank in RANKS:
        delta = dst.counts[rank - 1] - src.counts[rank - 1]
        if delta == 1:
            draw = rank
        elif delta == -1:
            discard = rank
    return draw, discard


def transition_text(src: Node, dst: Node) -> str:
    draw, discard = transition_tiles(src, dst)
    if draw is None or discard is None:
        return ""
    return f"ツモ{tile_text(draw)} / 打{tile_text(discard)}"


def build_real_graph_data() -> tuple[dict[str, Node], dict[str, set[str]], list[tuple[str, str]]]:
    nodes = build_base_nodes()
    undirected_edges = build_undirected_edges(nodes)
    nodes = enrich_nodes(nodes, undirected_edges, default_score)
    directed_edges = build_directed_edges(nodes, undirected_edges)
    return nodes, undirected_edges, directed_edges


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_dot(
    path: Path,
    nodes: dict[str, Node],
    directed_edges: list[tuple[str, str]],
) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("digraph six_shape_graph {\n")
        file.write('  rankdir="RL";\n')
        file.write('  node [shape=box, fontname="Meiryo"];\n')
        for shape in sorted(nodes):
            node = nodes[shape]
            label = (
                f"{shape}\\n"
                f"u={node.ukeire_count}, t={node.ukeire_type_count}\\n"
                f"g={node.improve_neighbor_count}, "
                f"max={node.max_neighbor_ukeire_count}, "
                f"avg={node.avg_neighbor_ukeire_count:.2f}"
            )
            file.write(f'  "{shape}" [label="{label}"];\n')
        for src, dst in directed_edges:
            file.write(f'  "{src}" -> "{dst}";\n')
        file.write("}\n")


def node_card_html(
    node: Node,
    *,
    css_class: str = "",
    relation: str = "",
) -> str:
    relation_html = f'<div class="relation">{html.escape(relation)}</div>' if relation else ""
    return f"""
    <section class="node-card {html.escape(css_class, quote=True)}">
      {relation_html}
      <h2>{html.escape(node.shape + WEST_PAIR_TEXT)}</h2>
      {hand_html(node)}
      <dl>
        <dt>受け入れ牌種</dt><dd>{ukeire_html(node)}</dd>
        <dt>受け入れ種類数</dt><dd>{node.ukeire_type_count}</dd>
        <dt>受け入れ枚数</dt><dd>{node.ukeire_count}</dd>
        <dt>改善隣接Node数</dt><dd>{node.improve_neighbor_count}</dd>
        <dt>隣接Node最大受け入れ枚数</dt><dd>{node.max_neighbor_ukeire_count}</dd>
        <dt>隣接Node平均受け入れ枚数</dt><dd>{node.avg_neighbor_ukeire_count:.2f}</dd>
        <dt>score</dt><dd><code>{html.escape(score_text(node.score))}</code></dd>
      </dl>
    </section>
    """


def write_visualizer_html(
    path: Path,
    nodes: dict[str, Node],
    undirected_edges: dict[str, set[str]],
    directed_edges: list[tuple[str, str]],
    selected_shape: str,
) -> None:
    outgoing = sorted(dst for src, dst in directed_edges if src == selected_shape)
    incoming = sorted(src for src, dst in directed_edges if dst == selected_shape)
    directed_set = set(directed_edges)
    same_rank_neighbors = sorted(
        neighbor
        for neighbor in undirected_edges[selected_shape]
        if (selected_shape, neighbor) not in directed_set
        and (neighbor, selected_shape) not in directed_set
    )

    selected = nodes[selected_shape]
    outgoing_cards = "\n".join(
        node_card_html(nodes[shape], css_class="better", relation=f"{selected_shape} -> {shape}")
        for shape in outgoing
    ) or '<p class="empty">改善先はありません。</p>'
    incoming_cards = "\n".join(
        node_card_html(nodes[shape], css_class="worse", relation=f"{shape} -> {selected_shape}")
        for shape in incoming
    ) or '<p class="empty">このNodeへ向かう改善元はありません。</p>'
    same_cards = "\n".join(
        node_card_html(nodes[shape], css_class="same", relation=f"{selected_shape} -- {shape}")
        for shape in same_rank_neighbors
    ) or '<p class="empty">同格の隣接Nodeはありません。</p>'

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>6枚形変化木 Visualizer - {html.escape(selected_shape + WEST_PAIR_TEXT)}</title>
  <style>
    body {{
      font-family: "Meiryo", system-ui, sans-serif;
      margin: 24px;
      background: #f6f7f9;
      color: #202124;
    }}
    header, .node-card {{
      background: white;
      border: 1px solid #d9dde3;
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }}
    header {{ margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 0 0 10px; font-size: 19px; }}
    h3 {{ margin: 28px 0 12px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 14px;
    }}
    .selected {{
      border-color: #2f6feb;
      background: #f7fbff;
      margin-bottom: 18px;
    }}
    .better {{ border-left: 6px solid #1a7f37; }}
    .worse {{ border-left: 6px solid #cf222e; }}
    .same {{ border-left: 6px solid #8c959f; }}
    .relation {{
      color: #57606a;
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .tile {{
      width: 33px;
      height: 45px;
      margin-right: 2px;
      vertical-align: middle;
    }}
    .tiles {{ white-space: nowrap; margin: 8px 0 12px; }}
    .ukeire-list {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .ukeire {{
      display: inline-flex;
      align-items: end;
      gap: 2px;
      margin-right: 4px;
    }}
    .count {{
      font-size: 12px;
      color: #57606a;
      margin-left: -1px;
    }}
    dl {{
      display: grid;
      grid-template-columns: 150px 1fr;
      gap: 6px 10px;
      margin: 0;
    }}
    dt {{ color: #57606a; }}
    dd {{ margin: 0; }}
    .summary {{
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      color: #57606a;
    }}
    .missing-tile {{
      display: inline-block;
      border: 1px solid #d0d7de;
      padding: 8px 4px;
      background: #fff8c5;
    }}
    .empty {{ color: #57606a; }}
  </style>
</head>
<body>
  <header>
    <h1>6枚形 + 西西 変化チェック</h1>
    <div class="summary">
      <span>選択Node: <strong>{html.escape(selected_shape + WEST_PAIR_TEXT)}</strong></span>
      <span>改善先: {len(outgoing)}</span>
      <span>改善元: {len(incoming)}</span>
      <span>同格隣接: {len(same_rank_neighbors)}</span>
      <span>全隣接: {len(undirected_edges[selected_shape])}</span>
    </div>
  </header>

  {node_card_html(selected, css_class="selected", relation="selected")}

  <h3>改善先: selected -> better</h3>
  <div class="grid">{outgoing_cards}</div>

  <h3>改善元: worse -> selected</h3>
  <div class="grid">{incoming_cards}</div>

  <h3>同格隣接: score同点</h3>
  <div class="grid">{same_cards}</div>
</body>
</html>
""",
        encoding="utf-8",
    )


def score_text(score: tuple[float, ...]) -> str:
    return "(" + ", ".join(f"{value:.6g}" for value in score) + ")"


def output_graph(
    nodes: dict[str, Node],
    undirected_edges: dict[str, set[str]],
    directed_edges: list[tuple[str, str]],
    prefix: Path,
) -> None:
    distances = distance_to_final(nodes, directed_edges)
    node_rows = []
    for shape in sorted(nodes):
        node = nodes[shape]
        node_rows.append(
            {
                "shape": shape,
                "hand": shape + WEST_PAIR_TEXT,
                "shape_name": node.shape_name,
                "ukeire_tiles": " ".join(tile_text(tile) for tile in node.ukeire_tiles),
                "ukeire_type_count": node.ukeire_type_count,
                "ukeire_count": node.ukeire_count,
                "fixed_ryanmen_count": node.fixed_ryanmen_count,
                "improve_neighbor_count": node.improve_neighbor_count,
                "max_neighbor_ukeire_count": node.max_neighbor_ukeire_count,
                "avg_neighbor_ukeire_count": f"{node.avg_neighbor_ukeire_count:.6f}",
                "score": score_text(node.score),
                "distance_to_final": distances[shape],
                "neighbor_count": len(undirected_edges[shape]),
                "neighbors": " ".join(sorted(undirected_edges[shape])),
            }
        )
    node_rows.sort(
        key=lambda row: (
            -int(row["ukeire_count"]),
            -int(row["ukeire_type_count"]),
            str(row["shape"]),
        )
    )

    edge_rows = [
        {
            "from": src,
            "to": dst,
            "change": transition_text(nodes[src], nodes[dst]),
            "from_score": score_text(nodes[src].score),
            "to_score": score_text(nodes[dst].score),
            "from_ukeire_count": nodes[src].ukeire_count,
            "to_ukeire_count": nodes[dst].ukeire_count,
            "from_fixed_ryanmen_count": nodes[src].fixed_ryanmen_count,
            "to_fixed_ryanmen_count": nodes[dst].fixed_ryanmen_count,
        }
        for src, dst in directed_edges
    ]

    write_csv(
        prefix.with_name(prefix.name + "_nodes.csv"),
        [
            "shape",
            "hand",
            "shape_name",
            "ukeire_tiles",
            "ukeire_type_count",
            "ukeire_count",
            "fixed_ryanmen_count",
            "improve_neighbor_count",
            "max_neighbor_ukeire_count",
            "avg_neighbor_ukeire_count",
            "score",
            "distance_to_final",
            "neighbor_count",
            "neighbors",
        ],
        node_rows,
    )
    write_csv(
        prefix.with_name(prefix.name + "_directed_edges.csv"),
        [
            "from",
            "to",
            "change",
            "from_score",
            "to_score",
            "from_ukeire_count",
            "to_ukeire_count",
            "from_fixed_ryanmen_count",
            "to_fixed_ryanmen_count",
        ],
        edge_rows,
    )
    write_dot(prefix.with_suffix(".dot"), nodes, directed_edges)


def build_real_graph(prefix: Path) -> None:
    nodes, undirected_edges, directed_edges = build_real_graph_data()
    output_graph(nodes, undirected_edges, directed_edges, prefix)

    undirected_edge_count = sum(len(neighbors) for neighbors in undirected_edges.values()) // 2
    print(f"nodes: {len(nodes)}")
    print(f"undirected_edges: {undirected_edge_count}")
    print(f"directed_edges: {len(directed_edges)}")
    print(f"nodes_csv: {prefix.with_name(prefix.name + '_nodes.csv')}")
    print(f"directed_edges_csv: {prefix.with_name(prefix.name + '_directed_edges.csv')}")
    print(f"dot: {prefix.with_suffix('.dot')}")


def write_visualizer_html(
    path: Path,
    nodes: dict[str, Node],
    undirected_edges: dict[str, set[str]],
    directed_edges: list[tuple[str, str]],
    selected_shape: str,
) -> None:
    """動的にNode選択できる、到達改善グラフHTMLを出力する。"""

    outgoing_map: dict[str, list[str]] = {shape: [] for shape in nodes}
    incoming_map: dict[str, list[str]] = {shape: [] for shape in nodes}
    for src, dst in directed_edges:
        outgoing_map[src].append(dst)
        incoming_map[dst].append(src)
    for values in outgoing_map.values():
        values.sort()
    for values in incoming_map.values():
        values.sort()
    transitions = {}
    for src, dst in directed_edges:
        draw, discard = transition_tiles(nodes[src], nodes[dst])
        transitions[f"{src}->{dst}"] = {
            "draw": "" if draw is None else tile_text(draw),
            "discard": "" if discard is None else tile_text(discard),
            "text": transition_text(nodes[src], nodes[dst]),
        }
    distances = distance_to_final(nodes, directed_edges)

    visualizer_nodes = {}
    for shape, node in nodes.items():
        change_tiles = []
        seen_change_tiles = set()
        for dst in outgoing_map[shape]:
            draw, _discard = transition_tiles(node, nodes[dst])
            if draw is not None and draw not in seen_change_tiles:
                seen_change_tiles.add(draw)
                change_tiles.append(draw)
        visualizer_nodes[shape] = {
            "hand": shape + WEST_PAIR_TEXT,
            "shapeName": node.shape_name,
            "handTiles": [tile_text(tile) for tile in hand_tiles(node)],
            "ukeireTiles": [
                {
                    "tile": tile_text(tile),
                    "remaining": 2 if tile == WEST else 4 - node.counts[tile - 1],
                }
                for tile in node.ukeire_tiles
            ],
            "changeTiles": [
                {
                    "tile": tile_text(tile),
                    "remaining": candidate_remaining(node.counts, tile),
                }
                for tile in sorted(change_tiles)
            ],
            "ukeireTypeCount": node.ukeire_type_count,
            "ukeireCount": node.ukeire_count,
            "fixedRyanmenCount": node.fixed_ryanmen_count,
            "improveNeighborCount": node.improve_neighbor_count,
            "maxNeighborUkeireCount": node.max_neighbor_ukeire_count,
            "avgNeighborUkeireCount": round(node.avg_neighbor_ukeire_count, 6),
            "distanceToFinal": distances[shape],
            "score": score_text(node.score),
        }

    data_json = json.dumps(
        {
            "initialShape": selected_shape,
            "nodes": visualizer_nodes,
            "outgoing": outgoing_map,
            "incoming": incoming_map,
            "undirected": {shape: sorted(neighbors) for shape, neighbors in undirected_edges.items()},
            "transitions": transitions,
            "tileImages": {
                "3z": tile_image_path(WEST).as_uri(),
                **{f"{rank}m": tile_image_path(rank).as_uri() for rank in RANKS},
            },
        },
        ensure_ascii=False,
    )

    template = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>6枚形 + 西西 変化グラフ</title>
  <style>
    body {
      font-family: "Meiryo", system-ui, sans-serif;
      margin: 24px;
      background: #f6f7f9;
      color: #202124;
    }
    header, .panel, .node-card {
      background: white;
      border: 1px solid #d9dde3;
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }
    header { margin-bottom: 14px; }
    h1 { margin: 0 0 10px; font-size: 24px; }
    h2 { margin: 0 0 10px; font-size: 17px; }
    .controls {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    input, select, button {
      font: inherit;
      padding: 7px 10px;
      border: 1px solid #d0d7de;
      border-radius: 8px;
      background: white;
    }
    button {
      cursor: pointer;
      background: #0969da;
      color: white;
      border-color: #0969da;
    }
    button.secondary {
      background: #f6f8fa;
      color: #24292f;
      border-color: #d0d7de;
    }
    .summary {
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      color: #57606a;
      margin-top: 10px;
    }
    #graphWrap {
      position: relative;
      min-height: 560px;
      overflow: auto;
      border: 1px solid #d9dde3;
      border-radius: 12px;
      background: #fff;
      margin-top: 14px;
    }
    #graph {
      position: relative;
      min-width: 900px;
      min-height: 560px;
    }
    #edges {
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: visible;
    }
    .node-card {
      position: absolute;
      width: 250px;
      box-sizing: border-box;
      padding: 12px;
    }
    .node-card.selected {
      border: 2px solid #0969da;
      background: #f0f6ff;
    }
    .node-card.sink {
      border-left: 7px solid #1a7f37;
    }
    .node-card h2 {
      margin: 0 0 8px;
      font-size: 16px;
    }
    .shape-name {
      color: #0969da;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .tile {
      width: 33px;
      height: 45px;
      margin-right: 2px;
      vertical-align: middle;
    }
    .tiles {
      white-space: nowrap;
      margin: 8px 0 10px;
    }
    .ukeire-list {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .ukeire {
      display: inline-flex;
      align-items: end;
      gap: 2px;
      margin-right: 4px;
    }
    .count {
      font-size: 12px;
      color: #57606a;
      margin-left: -1px;
    }
    dl {
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 4px 8px;
      margin: 0;
      font-size: 13px;
    }
    dt { color: #57606a; }
    dd { margin: 0; }
    .path-list {
      margin: 0;
      padding-left: 22px;
      line-height: 1.7;
    }
    .empty { color: #57606a; }
    .edge {
      stroke: #57606a;
      stroke-width: 1.6;
      fill: none;
      marker-end: url(#arrow);
    }
    .edge.direct {
      stroke: #0969da;
      stroke-width: 2.2;
    }
  </style>
</head>
<body>
  <header>
    <h1>6枚形 + 西西 変化グラフ</h1>
    <div>選択Nodeから、scoreが上がる有向Edgeを最終形まで辿って表示します。推移簡約はしていません。</div>
    <div class="controls">
      <label>形指定:
        <input id="shapeInput" list="shapeList" placeholder="例: 344555m">
      </label>
      <datalist id="shapeList"></datalist>
      <button id="showButton">表示</button>
      <button id="randomButton" class="secondary">ランダム</button>
      <label>最大表示Node:
        <select id="limitSelect">
          <option value="80">80</option>
          <option value="150" selected>150</option>
          <option value="300">300</option>
          <option value="99999">全て</option>
        </select>
      </label>
    </div>
    <div class="summary">
      <span>選択Node: <strong id="selectedLabel"></strong></span>
      <span>到達Node: <strong id="reachableCount"></strong></span>
      <span>到達Edge: <strong id="reachableEdgeCount"></strong></span>
      <span>最終形: <strong id="sinkCount"></strong></span>
      <span id="limitNotice"></span>
    </div>
  </header>

  <section class="panel">
    <h2>主な到達パス</h2>
    <ol id="pathList" class="path-list"></ol>
  </section>

  <div id="graphWrap">
    <div id="graph">
      <svg id="edges">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#57606a"></path>
          </marker>
        </defs>
      </svg>
    </div>
  </div>

  <script id="graph-data" type="application/json">__DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById("graph-data").textContent);
    const shapes = Object.keys(data.nodes).sort();
    const shapeList = document.getElementById("shapeList");
    const graph = document.getElementById("graph");
    const edgesSvg = document.getElementById("edges");
    const shapeInput = document.getElementById("shapeInput");
    const limitSelect = document.getElementById("limitSelect");

    for (const shape of shapes) {
      const option = document.createElement("option");
      option.value = shape;
      shapeList.appendChild(option);
    }

    function tileImg(tile) {
      const src = data.tileImages[tile];
      return `<img class="tile" src="${src}" alt="${tile}" title="${tile}">`;
    }

    function tileListHtml(items) {
      return items.map(item =>
        `<span class="ukeire">${tileImg(item.tile)}<span class="count">x${item.remaining}</span></span>`
      ).join("");
    }

    function nodeHtml(shape, node, isSelected, isSink) {
      const hand = node.handTiles.map(tileImg).join("");
      const ukeire = tileListHtml(node.ukeireTiles);
      const changes = tileListHtml(node.changeTiles);
      const classes = ["node-card"];
      if (isSelected) classes.push("selected");
      if (isSink) classes.push("sink");
      return `
        <section class="${classes.join(" ")}" id="node-${shape}">
          <h2>${node.hand}</h2>
          <div class="shape-name">${node.shapeName}</div>
          <div class="tiles">${hand}</div>
          <dl>
            <dt>受け入れ</dt><dd>${ukeire || "-"}</dd>
            <dt>種類数</dt><dd>${node.ukeireTypeCount}</dd>
            <dt>枚数</dt><dd>${node.ukeireCount}</dd>
            <dt>確定リャンメン</dt><dd>${node.fixedRyanmenCount}</dd>
            <dt>改善隣接</dt><dd>${node.improveNeighborCount}</dd>
            <dt>隣接max</dt><dd>${node.maxNeighborUkeireCount}</dd>
            <dt>隣接avg</dt><dd>${node.avgNeighborUkeireCount.toFixed(2)}</dd>
            <dt>変化牌</dt><dd>${changes || "-"}</dd>
            <dt>最終形まで</dt><dd>${node.distanceToFinal}</dd>
            <dt>score</dt><dd><code>${node.score}</code></dd>
          </dl>
        </section>
      `;
    }

    function reachableFrom(start, limit) {
      const depth = new Map([[start, 0]]);
      const queue = [start];
      const edgeSet = new Set();
      let truncated = false;

      while (queue.length) {
        const src = queue.shift();
        const nextDepth = depth.get(src) + 1;
        for (const dst of data.outgoing[src] || []) {
          edgeSet.add(`${src}\t${dst}`);
          if (!depth.has(dst)) {
            if (depth.size >= limit) {
              truncated = true;
              continue;
            }
            depth.set(dst, nextDepth);
            queue.push(dst);
          }
        }
      }
      const visible = new Set(depth.keys());
      const visibleEdges = [...edgeSet]
        .map(key => key.split("\t"))
        .filter(([src, dst]) => visible.has(src) && visible.has(dst));
      return { depth, visibleEdges, truncated };
    }

    function longestPaths(start, visibleEdges, maxCount = 12) {
      const out = new Map();
      for (const [src, dst] of visibleEdges) {
        if (!out.has(src)) out.set(src, []);
        out.get(src).push(dst);
      }
      for (const values of out.values()) {
        values.sort((a, b) => {
          const na = data.nodes[a];
          const nb = data.nodes[b];
          return nb.ukeireCount - na.ukeireCount || a.localeCompare(b);
        });
      }
      const result = [];
      function walk(shape, path) {
        const next = out.get(shape) || [];
        if (!next.length) {
          result.push(path);
          return;
        }
        for (const dst of next) {
          if (path.includes(dst)) continue;
          walk(dst, [...path, dst]);
          if (result.length >= maxCount) return;
        }
      }
      walk(start, [start]);
      result.sort((a, b) => b.length - a.length);
      return result.slice(0, maxCount);
    }

    function render(start) {
      if (!data.nodes[start]) {
        alert(`Unknown shape: ${start}`);
        return;
      }
      shapeInput.value = start;
      const limit = Number(limitSelect.value);
      const { depth, visibleEdges, truncated } = reachableFrom(start, limit);
      const shapesByDepth = new Map();
      for (const [shape, d] of depth.entries()) {
        if (!shapesByDepth.has(d)) shapesByDepth.set(d, []);
        shapesByDepth.get(d).push(shape);
      }
      for (const values of shapesByDepth.values()) {
        values.sort((a, b) => {
          const na = data.nodes[a];
          const nb = data.nodes[b];
          return nb.ukeireCount - na.ukeireCount || a.localeCompare(b);
        });
      }

      const depthCount = Math.max(...depth.values()) + 1;
      const columnWidth = 315;
      const rowHeight = 265;
      const cardWidth = 250;
      const cardHeight = 220;
      let maxRows = 1;
      for (const values of shapesByDepth.values()) maxRows = Math.max(maxRows, values.length);
      graph.style.width = `${Math.max(900, depthCount * columnWidth + 80)}px`;
      graph.style.height = `${Math.max(560, maxRows * rowHeight + 80)}px`;
      edgesSvg.setAttribute("width", graph.style.width);
      edgesSvg.setAttribute("height", graph.style.height);

      const sinks = [];
      const positions = new Map();
      let cards = "";
      for (const [d, values] of [...shapesByDepth.entries()].sort((a, b) => a[0] - b[0])) {
        values.forEach((shape, row) => {
          const x = 30 + d * columnWidth;
          const y = 30 + row * rowHeight;
          positions.set(shape, { x, y });
          const isSink = !(data.outgoing[shape] || []).some(dst => depth.has(dst));
          if (isSink) sinks.push(shape);
          cards += nodeHtml(
              shape,
              data.nodes[shape],
              shape === start,
              isSink
            )
            .replace("<section", `<section style="left:${x}px;top:${y}px"`);
        });
      }
      graph.querySelectorAll(".node-card").forEach(el => el.remove());
      graph.insertAdjacentHTML("beforeend", cards);

      const defs = edgesSvg.querySelector("defs").outerHTML;
      edgesSvg.innerHTML = defs;
      for (const [src, dst] of visibleEdges) {
        const p1 = positions.get(src);
        const p2 = positions.get(dst);
        if (!p1 || !p2) continue;
        const x1 = p1.x + cardWidth;
        const y1 = p1.y + cardHeight / 2;
        const x2 = p2.x;
        const y2 = p2.y + cardHeight / 2;
        const mid = (x1 + x2) / 2;
        const cls = src === start ? "edge direct" : "edge";
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("class", cls);
        path.setAttribute("d", `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2 - 8} ${y2}`);
        edgesSvg.appendChild(path);
      }

      document.getElementById("selectedLabel").textContent = data.nodes[start].hand;
      document.getElementById("reachableCount").textContent = depth.size;
      document.getElementById("reachableEdgeCount").textContent = visibleEdges.length;
      document.getElementById("sinkCount").textContent = sinks.length;
      document.getElementById("limitNotice").textContent = truncated ? "表示上限により一部省略" : "";

      const pathList = document.getElementById("pathList");
      const paths = longestPaths(start, visibleEdges);
      pathList.innerHTML = paths.length
        ? paths.map(path => `<li>${path.map(shape => data.nodes[shape].hand).join(" → ")}</li>`).join("")
        : '<li class="empty">このNodeは最終形です。</li>';
    }

    document.getElementById("showButton").addEventListener("click", () => {
      const value = shapeInput.value.trim().replace(/33z$/, "");
      render(value);
    });
    document.getElementById("randomButton").addEventListener("click", () => {
      const shape = shapes[Math.floor(Math.random() * shapes.length)];
      render(shape);
    });
    limitSelect.addEventListener("change", () => {
      const value = shapeInput.value.trim().replace(/33z$/, "");
      render(value || data.initialShape);
    });
    shapeInput.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        document.getElementById("showButton").click();
      }
    });

    render(data.initialShape);
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("__DATA__", data_json), encoding="utf-8")


def run_visualizer(
    *,
    shape: str | None,
    seed: int | None,
    output: Path,
) -> None:
    nodes, undirected_edges, directed_edges = build_real_graph_data()
    if shape:
        selected_shape = shape.removesuffix(WEST_PAIR_TEXT)
        if selected_shape not in nodes:
            raise ValueError(f"unknown node shape: {shape}")
    else:
        rng = random.Random(seed)
        selected_shape = rng.choice(sorted(nodes))
    write_visualizer_html(output, nodes, undirected_edges, directed_edges, selected_shape)
    print(f"selected: {selected_shape + WEST_PAIR_TEXT}")
    print(f"visualizer_html: {output}")


def build_dummy_graph(prefix: Path) -> tuple[dict[str, Node], list[tuple[str, str]]]:
    nodes = {
        "A": Node("A", (0,) * 9, "dummy", tuple(), 0, 20),
        "B": Node("B", (0,) * 9, "dummy", tuple(), 0, 16, good_shape_score=1),
        "C": Node("C", (0,) * 9, "dummy", tuple(), 0, 16, good_shape_score=0),
    }
    undirected_edges = {
        "A": {"B", "C"},
        "B": {"A", "C"},
        "C": {"A", "B"},
    }
    nodes = enrich_nodes(nodes, undirected_edges, dummy_score)
    directed_edges = build_directed_edges(nodes, undirected_edges)
    output_graph(nodes, undirected_edges, directed_edges, prefix)
    return nodes, directed_edges


def run_dummy_test(prefix: Path) -> None:
    _nodes, directed_edges = build_dummy_graph(prefix)
    expected = [("B", "A"), ("C", "A")]
    if directed_edges != expected:
        raise AssertionError(f"dummy edge mismatch: expected={expected}, actual={directed_edges}")
    print("dummy_test: ok")
    print("directed_edges:", " ".join(f"{src}->{dst}" for src, dst in directed_edges))
    print(f"nodes_csv: {prefix.with_name(prefix.name + '_nodes.csv')}")
    print(f"directed_edges_csv: {prefix.with_name(prefix.name + '_directed_edges.csv')}")
    print(f"dot: {prefix.with_suffix('.dot')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    parser.add_argument(
        "--visualize",
        nargs="?",
        const="",
        metavar="SHAPE",
        help="ランダムNode、または指定Nodeの変化先をHTML表示する。例: --visualize 344555m",
    )
    parser.add_argument("--visualizer-output", type=Path, default=DEFAULT_VISUALIZER_OUTPUT)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--dummy-test",
        action="store_true",
        help="A/B/CのダミーNodeで期待Edgeを検証して出力する",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dummy_test:
        run_dummy_test(args.prefix.with_name(args.prefix.name + "_dummy"))
    elif args.visualize is not None:
        run_visualizer(
            shape=args.visualize or None,
            seed=args.seed,
            output=args.visualizer_output,
        )
    else:
        build_real_graph(args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
