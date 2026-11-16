"""Forward road/building candidates: a visible building is not proof of no road."""
import numpy as np

from ..findings import candidate, unknown


def detect_road_presence(road: np.ndarray, building: np.ndarray) -> dict:
    h, w = road.shape
    y0, y1 = int(h * .30), int(h * .68)
    x0, x1 = int(w * .32), int(w * .68)
    a, b = road[y0:y1, x0:x1], building[y0:y1, x0:x1]
    if not a.size:
        return unknown("전방 도로 존재 영역이 너무 작습니다.")
    road_ratio = float(np.mean(a))
    building_ratio = float(np.mean(b))
    scores = {
        "forward_road_ratio": round(road_ratio, 4),
        "forward_building_ratio": round(building_ratio, 4),
    }
    if road_ratio >= .24:
        result = candidate(
            True, "segformer_forward_road_candidate",
            "촬영 방향 전방 중앙에 도로 영역이 검출됐습니다.",
            min(.82, .55 + road_ratio * .4),
        )
    elif building_ratio >= .46 and road_ratio < .055:
        result = candidate(
            False, "segformer_building_obstruction_candidate",
            "전방 중앙에 건물이 우세하고 도로가 거의 없습니다. 건물 옆 도로와 촬영 위치를 직접 확인하세요.",
            min(.83, .53 + building_ratio * .36),
        )
    else:
        result = unknown("전방 중앙에서 도로와 비도로를 확실하게 구분하지 못했습니다.")
    result["evidence_scores"] = scores
    result["roi"] = [x0, y0, x1, y1]
    return result
