"""Versioned, reviewed-data selection policy for the small first catalog."""

import re
from dataclasses import dataclass

from whisky.modules.discovery.public import ResearchConditions
from whisky.modules.research.contracts import ResearchCatalogSnapshot

SELECTION_POLICY_VERSION = "catalog-selection-v3-3"


@dataclass(frozen=True)
class ResearchSelection:
    version_indices: tuple[int, ...]
    candidate_indices: tuple[int, ...]
    unlisted_name: str | None = None
    unresolved: tuple[str, ...] = ()


def select_research(
    conditions: ResearchConditions,
    snapshot: ResearchCatalogSnapshot,
    selected_version_id: str | None,
) -> ResearchSelection:
    goal = conditions.goal
    starting = conditions.starting_bottle
    if starting is not None and not any(
        (item.release_id, item.item_id) == (starting.release_id, starting.item_id)
        for item in snapshot.items
    ):
        return ResearchSelection(
            (), (), unresolved=("起點酒款已不在目前已覆核資料中，請重新確認版本。",)
        )
    if (
        starting is None
        and selected_version_id is None
        and any(
            marker in goal for marker in ("不確定", "不清楚", "不記得", "先確認版本")
        )
    ):
        groups: dict[str, list[int]] = {}
        for item in snapshot.items:
            stem = item.name.split()[0]
            if len(stem) >= 3:
                groups.setdefault(stem, []).append(item.index)
        matching = [
            tuple(indices)
            for stem, indices in groups.items()
            if stem in goal and 2 <= len(indices) <= 5
        ]
        if len(matching) == 1:
            return ResearchSelection(matching[0], ())

    named = re.search(
        r"(?:推薦|查核|比較)\s*([A-Z][A-Za-z]*(?:\s+[A-Za-z][A-Za-z0-9]*){1,3})",
        goal,
    )
    if named is not None:
        target = named.group(1)
        if not any(
            target.casefold() in item.official_name.casefold()
            or target.casefold() in item.name.casefold()
            for item in snapshot.items
        ):
            return ResearchSelection((), (), target)

    eligible = [item for item in snapshot.items if item.eligible]
    if selected_version_id is not None:
        eligible = [
            item
            for item in eligible
            if str(item.bottle_version_id) != selected_version_id
        ]
    finding_new = conditions.entry == "existing_bottle" or any(
        marker in goal for marker in ("不同", "下一款", "其他")
    )
    if finding_new and starting is not None:
        eligible = [
            item
            for item in eligible
            if (item.release_id, item.item_id)
            != (starting.release_id, starting.item_id)
        ]
    named_eligible = [item for item in eligible if item.name in goal]
    if finding_new and any(marker in goal for marker in ("喜歡", "喝過")):
        eligible = [item for item in eligible if item.name not in goal]
    elif named_eligible and any(marker in goal for marker in ("查核", "推薦")):
        eligible = named_eligible
    known_tags = {tag for item in snapshot.items for tag in item.flavor_tags}
    unresolved = []
    for preference in conditions.preferences:
        if preference.strength != "hard":
            continue
        label = preference.description.strip()
        if preference.intent in {"prefer", "keep"} and label in known_tags:
            eligible = [item for item in eligible if label in item.flavor_tags]
        else:
            # Missing tags cannot prove that a hard negative or change is met.
            eligible = []
            unresolved.append(
                f"已覆核資料無法證實硬偏好「{label}」符合要求，未列為候選。"
            )

    def soft_score(item_index: int) -> int:
        item = snapshot.items[item_index - 1]
        return sum(
            (1 if preference.intent in {"prefer", "keep"} else -1)
            for preference in conditions.preferences
            if preference.strength == "soft"
            and preference.description.strip() in known_tags
            and preference.description.strip() in item.flavor_tags
            and preference.intent in {"prefer", "keep", "avoid"}
        )

    ordered = sorted(eligible, key=lambda item: -soft_score(item.index))
    return ResearchSelection(
        (), tuple(item.index for item in ordered[:3]), unresolved=tuple(unresolved)
    )
