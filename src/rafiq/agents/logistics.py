import hashlib
import hmac
import json
from typing import Any, Dict, List

from rafiq.config import settings
from rafiq.core.messages import BANNERS
from rafiq.core.state import AgentOutput, Finding
from rafiq.live.real import get_fleet_real
from rafiq.live.sim import get_fleet_sim, get_truck_temps_sim


def check_bus_overheat(fleet: List[Dict]) -> List[Dict]:
    alerts = []
    for bus in fleet:
        if bus.get("engine_temp_c", 0) > 100:
            alerts.append(
                {"bus_id": bus["bus_id"], "temp": bus["engine_temp_c"], "status": "OVERHEAT"}
            )
    return alerts


def check_cold_chain(
    truck_readings: List[Dict],
    chilled_max: float = 4.0,
    frozen_max: float = -18.0,
    gap_minutes: int = 30,
) -> List[Dict]:
    results = []
    for truck in truck_readings:
        readings = truck.get("readings", [])
        # check gaps
        # simplistic gap detection
        status = truck.get("status", "cold_chain_intact")
        if not readings:
            status = "insufficient_data"
        else:
            # check breach
            for r in readings:
                if r["temp_c"] > chilled_max:
                    status = "breached"
                    break
        results.append(
            {"truck_id": truck["truck_id"], "status": status, "readings_count": len(readings)}
        )
    return results


def generate_amin_certificate(truck_id: str, readings: List[Dict], status: str) -> Dict[str, Any]:
    # SHA-256 over readings
    canonical = json.dumps(readings, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    secret = settings.RAFIQ_AMIN_SECRET.encode("utf-8")
    signature = hmac.new(secret, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "truck": truck_id,
        "window": {
            "from": readings[0]["ts"] if readings else None,
            "to": readings[-1]["ts"] if readings else None,
        },
        "status": status,
        "readings_digest": digest,
        "signature": signature,
        "disclaimer": BANNERS["amin_disclaimer"],
        "data_source": "sim",
    }


def verify_amin_certificate(cert: Dict[str, Any], readings: List[Dict]) -> bool:
    canonical = json.dumps(readings, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != cert.get("readings_digest"):
        return False
    secret = settings.RAFIQ_AMIN_SECRET.encode("utf-8")
    expected_sig = hmac.new(secret, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, cert.get("signature", ""))


def logistics_agent(query: str, live_mode: str = "sim") -> AgentOutput:
    if live_mode == "real":
        fleet_data = get_fleet_real()
        if "error" in fleet_data:
            fleet = []
        else:
            fleet = fleet_data.get("data", [])
        truck_data = []  # real fleet would have temps
    else:
        fleet = get_fleet_sim()
        truck_data = get_truck_temps_sim()

    findings = []
    for bus in fleet:
        findings.append(
            Finding(
                source_id=f"bus_{bus['bus_id']}",
                excerpt=(
                    f"Bus {bus['bus_id']} at {bus['location']} "
                    f"engine {bus['engine_temp_c']}C status {bus['status']}"
                ),
                work="fleet_status",
                verified=False,
                topic_tags=["logistics", "bus"],
            )
        )
    for truck in truck_data:
        findings.append(
            Finding(
                source_id=f"truck_{truck['truck_id']}",
                excerpt=f"Truck {truck['truck_id']} cold chain {truck['status']}",
                work="truck_temps",
                verified=False,
                topic_tags=["logistics", "cold_chain"],
            )
        )

    disclaimers = [BANNERS["sim_data"] if live_mode == "sim" else ""]

    return AgentOutput(
        agent="logistics",
        status="ok" if findings else "insufficient_data",
        findings=findings,
        informational_only=True,
        disclaimers=[d for d in disclaimers if d],
        data_source=live_mode,
        extra={"fleet": fleet, "trucks": truck_data},
    )
