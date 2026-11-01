"""Single-writer paper runtime. All fills pass the verified gateway; no signing is available."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from pydantic import ValidationError

from aegis.connectors.hskswap_v3 import HSKSwapConnector
from aegis.connectors.paper import PaperConnector
from aegis.connectors.rpc import DiscoveryError
from aegis.data import load_network
from aegis.execution.gateway import ExecutionGateway
from aegis.risk.engine import RiskRejected
from aegis.risk.policy import CAPS, AgentParams, entry_check, exit_reason
from aegis.store.db import LedgerError, PaperLedger
from aegis.strategy.arbitrage import evaluate as evaluate_cycle
from aegis.strategy.mean_reversion import evaluate


def dec(value) -> str:
    return format(Decimal(value), "f")


class PaperRuntime:
    def __init__(
        self,
        path: Path,
        *,
        connector=None,
        allow_test_connectors=False,
        halted: threading.Event | None = None,
        emergency: threading.Event | None = None,
    ):
        self.live = connector or HSKSwapConnector(load_network("mainnet"))
        self.halted, self.emergency = halted or threading.Event(), emergency or threading.Event()
        self.halted.set()  # Every restart requires an explicit paper resume.
        self.ledger = PaperLedger(
            path, self.live.tokens["USDT"], 100 * 10 ** self.live.tokens["USDT"].decimals
        )
        self.params = AgentParams.model_validate(self.ledger.metadata("agent_params", {}))
        self.version = self.ledger.metadata("params_version", 1)
        self.running = False
        self.started_at = int(time.time())
        self.last_error = None
        self.last_tick_at = None
        self.tick_count = 0
        self.latest = self.ledger.observations(1)
        self.latest = self.latest[-1] if self.latest else None
        self.baseline = self.ledger.metadata("risk_baseline", {})
        if self.ledger.metadata("emergency", False):
            self.emergency.set()
        self.unwind = self.emergency.is_set()
        self.running = self.unwind or any(
            r["amount_raw"] and r["token"] != self.ledger.stable
            for r in self.ledger.balances().values()
        )
        self.gateway = ExecutionGateway(
            PaperConnector(self.live),
            self.ledger,
            allow_test_connectors=allow_test_connectors,
            before_fill=self._before_fill,
        )
        self.ledger.record(
            "recovered_paused",
            {"mode": "paper", "reason": "Process started; entries require explicit resume"},
        )

    def close(self):
        self.halted.set()
        self.ledger.close()
        self.live.close()

    def _positions(self, marks: dict[str, Decimal]) -> list[dict]:
        positions = []
        for address, row in self.ledger.balances().items():
            token, amount, cost = row["token"], row["amount_raw"], row["cost_usdt"]
            if token == self.ledger.stable or amount == 0:
                continue
            mark = marks[address]
            quantity = Decimal(amount) / 10**token.decimals
            value = quantity * mark
            clock = self.ledger.position_clock(token, mark)
            positions.append(
                {
                    "asset": token.asset_id,
                    "token_address": token.address,
                    "amount_raw": str(amount),
                    "quantity": dec(quantity),
                    "entry": dec(cost / quantity),
                    "cost_usdt": dec(cost),
                    "mark": dec(mark),
                    "value_usdt": dec(value),
                    "unrealized_pnl_usdt": dec(value - cost),
                    "unrealized_pnl_pct": dec((value / cost - 1) * 100) if cost else "0",
                    "opened_at": clock["opened_at"],
                    "peak_price": dec(clock["peak_price"]),
                    "stop_price": dec(cost / quantity * (1 - self.params.stop_loss_pct / 100)),
                    "take_profit_price": dec(
                        cost / quantity * (1 + self.params.take_profit_pct / 100)
                    ),
                }
            )
        return positions

    def _before_fill(self, quote, marks):
        if (
            quote.route.tokens[-1] == self.ledger.stable
            and quote.route.tokens[0] != self.ledger.stable
        ):
            return  # Risk-reducing exits keep per-trade/liquidity/slippage gates, even while paused.
        if self.halted.is_set() or self.emergency.is_set() or not self.running:
            raise RiskRejected("Entries are paused or emergency stop is latched")
        nav = Decimal(self.ledger.pnl(marks)["nav_usdt"])
        positions = self._positions(marks)
        entry_check(
            nav=nav,
            input_value=Decimal(quote.amount_in_raw)
            / 10 ** quote.route.tokens[0].decimals
            * marks[quote.route.tokens[0].address.lower()],
            exposure=sum((Decimal(p["value_usdt"]) for p in positions), Decimal(0)),
            positions=len(positions),
            fills=self.ledger.fills(),
            now=int(time.time()),
            params=self.params,
        )
        if quote.route.tokens[-1] == self.ledger.stable:
            return
        if quote.route.tokens[-1].asset_id not in self.params.target_assets:
            raise RiskRejected("Target asset is disabled")
        if any(p["asset"] == quote.route.tokens[-1].asset_id for p in positions):
            raise RiskRejected("A position in this asset is already open")

    def _snapshot(self) -> tuple[dict, dict[str, Decimal]]:
        m = self.live.refresh()
        marks = {self.ledger.stable.address.lower(): Decimal(1)}
        markets = {}
        for pool in m.pools:
            if pool.token1 == "USDT":
                asset, price = pool.token0, pool.mid_token1_per_token0
            elif pool.token0 == "USDT":
                asset, price = pool.token1, Decimal(1) / pool.mid_token1_per_token0
            else:
                continue
            if asset not in {"WHSK", "WETH", "WBTC"}:
                continue
            marks[self.live.tokens[asset].address.lower()] = price
            markets[asset] = {
                "asset": asset,
                "price": dec(price),
                "pool": pool.address,
                "liquidity_raw": pool.active_liquidity_raw,
                "fee_pips": pool.fee_pips,
            }
        if any(self.live.tokens[a].address.lower() not in marks for a in self.params.target_assets):
            raise DiscoveryError("Selected asset has no verified direct settlement mark")
        if int(time.time()) - m.block_timestamp > 90:
            raise DiscoveryError("Market block is stale")
        return {
            "block_number": m.block_number,
            "block_hash": m.block_hash,
            "block_timestamp": m.block_timestamp,
            "markets": markets,
        }, marks

    def _circuit(self, pnl: dict, timestamp: int):
        nav = Decimal(pnl["nav_usdt"])
        day = timestamp // 86400
        if self.baseline.get("day") != day:
            self.baseline.update(day=day, day_nav=dec(nav))
        high = max(nav, Decimal(self.baseline.get("high_water", dec(nav))))
        self.baseline["high_water"] = dec(high)
        day_nav = Decimal(self.baseline["day_nav"])
        loss = max(Decimal(0), (day_nav - nav) / day_nav * 100) if day_nav else Decimal(100)
        drawdown = max(Decimal(0), (high - nav) / high * 100) if high else Decimal(100)
        self.baseline.update(daily_loss_pct=dec(loss), drawdown_pct=dec(drawdown))
        self.baseline["max_drawdown_pct"] = dec(
            max(drawdown, Decimal(self.baseline.get("max_drawdown_pct", "0")))
        )
        self.ledger.set_metadata("risk_baseline", self.baseline)
        if (loss >= 2 or drawdown >= 10) and not self.emergency.is_set():
            self.halted.set()
            self.emergency.set()
            self.unwind = True
            self.ledger.set_metadata("emergency", True)
            self.ledger.record(
                "circuit_breaker",
                {
                    "daily_loss_pct": dec(loss),
                    "drawdown_pct": dec(drawdown),
                    "action": "pause entries and request stable unwind",
                },
            )

    def _close_position(self, position: dict, marks: dict[str, Decimal], reason: str, key: str):
        token = self.live.tokens[position["asset"]]
        nav = Decimal(self.ledger.pnl(marks)["nav_usdt"])
        # Leave rounding margin under the atomic 10% NAV cap; large holdings unwind in chunks.
        limit = int(
            (
                nav * Decimal("0.099") / marks[token.address.lower()] * 10**token.decimals
            ).to_integral_value(rounding=ROUND_DOWN)
        )
        amount = min(int(position["amount_raw"]), limit)
        if amount <= 0:
            raise RiskRejected("Remaining value is too small for a bounded exit")
        signal_id = self.ledger.record(
            "exit_signal",
            {
                "asset": token.asset_id,
                "reason": reason,
                "amount_in_raw": str(amount),
                "mode": "paper",
            },
        )
        result = self.gateway.execute(key, token, self.ledger.stable, amount)
        self.ledger.record(
            "exit_executed",
            {
                "signal_id": signal_id,
                "reason": reason,
                "fill_id": result["id"],
                "asset": token.asset_id,
            },
        )

    def tick(self, *, evaluate_entries=True) -> dict:
        self.tick_count += 1
        self.last_tick_at = int(time.time())
        try:
            market, marks = self._snapshot()
            self.last_tick_at = int(time.time())
            self.last_error = None
            pnl = self.ledger.pnl(marks)
            self._circuit(pnl, market["block_timestamp"])
            positions = self._positions(marks)
            exiting = False
            for position in positions:
                reason = (
                    "panic_unwind"
                    if self.unwind
                    else exit_reason(position, self.params, self.last_tick_at)
                )
                if reason:
                    exiting = True
                    try:
                        self._close_position(
                            position,
                            marks,
                            reason,
                            f"exit:{position['asset']}:{position['opened_at']}:{market['block_hash']}:{self.tick_count}",
                        )
                    except (RiskRejected, LedgerError, DiscoveryError) as exc:
                        self.ledger.record(
                            "exit_blocked",
                            {"asset": position["asset"], "reason": str(exc), "trigger": reason},
                        )
            positions = self._positions(marks)
            if not positions:
                self.unwind = False
            history = self.ledger.observations(120)
            same_block = bool(history and history[-1]["block_hash"] == market["block_hash"])
            signals = []
            if not same_block:
                for asset in self.params.target_assets:
                    prices = [
                        Decimal(h["markets"][asset]["price"])
                        for h in history
                        if asset in h["markets"]
                    ]
                    prices.append(Decimal(market["markets"][asset]["price"]))
                    nav = Decimal(self.ledger.pnl(marks)["nav_usdt"])
                    size = nav * self.params.position_size_pct / 100
                    cost = (
                        Decimal(80)
                        + self.gateway.connector.terms.network_fee_usdt
                        * 2
                        / max(size, Decimal("0.000001"))
                        * 10000
                    )
                    z = {
                        "conservative": Decimal("2.5"),
                        "balanced": Decimal(2),
                        "aggressive": Decimal("1.75"),
                    }[self.params.risk_level]
                    signal = evaluate(asset, prices, z_threshold=z, modeled_cost_bps=cost)
                    payload = signal.model_dump(mode="json")
                    signals.append(payload)
                    if (
                        signal.action == "buy"
                        and evaluate_entries
                        and self.running
                        and not exiting
                        and not self.halted.is_set()
                    ):
                        try:
                            amount = int(size * 10**self.ledger.stable.decimals)
                            result = self.gateway.execute(
                                "signal:" + signal.id,
                                self.ledger.stable,
                                self.live.tokens[asset],
                                amount,
                            )
                            self.ledger.record(
                                "signal_executed", {"signal": payload, "fill_id": result["id"]}
                            )
                            break
                        except (RiskRejected, LedgerError, DiscoveryError) as exc:
                            self.ledger.record(
                                "risk_rejected", {"signal": payload, "reason": str(exc)}
                            )
                    else:
                        self.ledger.record(
                            "signal_skipped",
                            {
                                "signal": payload,
                                "reason": "Entries paused"
                                if self.halted.is_set()
                                else signal.reason,
                            },
                        )
                cycles = self.live.find_routes(self.ledger.stable, self.ledger.stable)
                self.ledger.record(
                    "arbitrage_scan",
                    {
                        "verified_cycles": len(cycles),
                        "reason": "No verified closed route"
                        if not cycles
                        else "Quotes include all route LP fees",
                    },
                )
                for route in cycles:
                    try:
                        amount = int(
                            Decimal(self.ledger.pnl(marks)["nav_usdt"])
                            * self.params.position_size_pct
                            / 100
                            * 10**self.ledger.stable.decimals
                        )
                        quote = self.live.quote_route(route, amount)
                        fee_raw = int(
                            self.gateway.connector.terms.network_fee_usdt
                            * 10**self.ledger.stable.decimals
                        )
                        cycle = evaluate_cycle(
                            quote,
                            extra_slippage_bps=self.gateway.connector.terms.extra_slippage_bps,
                            network_fee_raw=fee_raw,
                        )
                        self.ledger.record("arbitrage_signal", cycle.model_dump(mode="json"))
                        if (
                            cycle.action == "cycle"
                            and evaluate_entries
                            and self.running
                            and not self.halted.is_set()
                        ):
                            gross_profit = quote.amount_out_raw - amount
                            if gross_profit <= 0 or fee_raw * 100 > gross_profit * 25:
                                raise RiskRejected(
                                    "Modeled network expense exceeds 25% of expected cycle profit"
                                )
                            self.gateway.execute(
                                "cycle:" + cycle.id, self.ledger.stable, self.ledger.stable, amount
                            )
                    except (DiscoveryError, RiskRejected, LedgerError) as exc:
                        self.ledger.record("arbitrage_rejected", {"reason": str(exc)})
            fills = self.ledger.fills()
            if fills and fills[-1]["quote"]["block_hash"] != market["block_hash"]:
                market, marks = self._snapshot()
            pnl = self.ledger.pnl(marks)
            self._circuit(pnl, market["block_timestamp"])
            self.latest = {
                **market,
                "observed_at": self.last_tick_at,
                "pnl": pnl,
                "positions": self._positions(marks),
                "signals": signals,
            }
            if not same_block:
                self.ledger.observe(self.latest)
            return self.view()
        except (DiscoveryError, RiskRejected, LedgerError, ValueError) as exc:
            self.last_error = str(exc)
            self.ledger.record(
                "data_unavailable", {"reason": self.last_error, "action": "no new fill"}
            )
            return self.view()

    def view(self) -> dict:
        latest = self.latest or {}
        fresh = (
            bool(latest)
            and int(time.time()) - latest["block_timestamp"] <= 90
            and self.last_error is None
        )
        observations = self.ledger.observations(300)
        fills = self.ledger.fills()
        return {
            "mode": "paper",
            "chain_id": self.live.chain_id,
            "running": self.running,
            "paused": self.halted.is_set(),
            "emergency": self.emergency.is_set(),
            "unwind_pending": self.unwind,
            "started_at": self.started_at,
            "uptime_seconds": int(time.time()) - self.started_at,
            "tick_count": self.tick_count,
            "last_tick_at": self.last_tick_at,
            "data_status": "LIVE"
            if fresh and self.live.name == "hskswap_v3"
            else "TEST_FIXTURE"
            if fresh
            else "UNAVAILABLE"
            if not latest
            else "STALE",
            "data_source": self.live.name,
            "last_error": self.last_error,
            "block_number": latest.get("block_number"),
            "block_hash": latest.get("block_hash"),
            "block_timestamp": latest.get("block_timestamp"),
            "markets": latest.get("markets", {}),
            "pnl": latest.get("pnl") if fresh else None,
            "last_known_pnl": latest.get("pnl"),
            "positions": latest.get("positions", []),
            "valuation_fresh": fresh,
            "signals": latest.get("signals", []),
            "params": self.params.model_dump(mode="json"),
            "params_version": self.version,
            "caps": CAPS,
            "risk": self.baseline,
            "trades_this_hour": sum(
                f["created_at"] // 3600 == int(time.time()) // 3600 for f in fills
            ),
            "trades_today": sum(
                f["created_at"] // 86400 == int(time.time()) // 86400 for f in fills
            ),
            "fills": list(reversed(fills[-40:])),
            "decisions": self.ledger.decisions(),
            "equity_curve": [{"at": o["observed_at"], **o["pnl"]} for o in observations],
            "price_history": [
                {
                    "at": o["observed_at"],
                    "block": o["block_number"],
                    "prices": {asset: m["price"] for asset, m in o["markets"].items()},
                }
                for o in observations
            ],
            "costs": self.gateway.connector.terms.model_dump(mode="json"),
            "live_enabled": False,
            "public_deployment": None,
            "disclosure": "PAPER · live HSKSwap quotes, virtual funds and modeled costs. Decisions are local; no public on-chain verification is claimed.",
        }

    def set_params(self, patch: dict, expected_version: int) -> dict:
        if expected_version != self.version:
            raise ValueError("Settings changed; refresh before applying this change")
        previous = self.params.model_dump(mode="json")
        try:
            candidate = AgentParams.model_validate({**previous, **patch})
        except ValidationError as exc:
            raise ValueError(
                "PAPER settings refused: "
                + "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
            ) from None
        values = candidate.model_dump(mode="json")
        changes = {
            k: {"before": previous[k], "after": v} for k, v in values.items() if v != previous[k]
        }
        self.ledger.db.execute("BEGIN IMMEDIATE")
        try:
            self.ledger.set_metadata("agent_params", values)
            self.ledger.set_metadata("params_version", self.version + 1)
            self.ledger.record(
                "params_changed", {"changes": changes, "mode": "paper", "on_chain": False}
            )
            self.ledger.db.execute("COMMIT")
        except Exception:
            self.ledger.db.execute("ROLLBACK")
            raise
        self.params, self.version = candidate, self.version + 1
        return {
            "changes": changes,
            "params_version": self.version,
            "params": values,
            "mode": "paper",
        }

    def control(
        self, action: str, *, acknowledgement: str | None = None, confirmation: str | None = None
    ) -> dict:
        if action == "pause":
            self.halted.set()
        elif action == "resume":
            if acknowledgement != "AUTHORIZE_PAPER_AUTOMATION":
                raise ValueError("Acknowledge paper automation; funds and fills remain virtual")
            if self.emergency.is_set():
                raise ValueError("Emergency stop is latched; review and clear it before resuming")
            self.running = True
            self.halted.clear()
        elif action == "panic":
            self.halted.set()
            self.emergency.set()
            self.unwind = True
            self.running = True  # Continue observations and bounded exits, with entries blocked.
            self.ledger.set_metadata("emergency", True)
        elif action == "clear_emergency":
            if acknowledgement != "REVIEW_AND_CLEAR_PAPER_STOP":
                raise ValueError("Explicit emergency-stop review is required")
            if not self.view()["valuation_fresh"] or self.view()["positions"]:
                raise ValueError("Obtain fresh marks and finish the stable unwind before clearing")
            self.emergency.clear()
            self.halted.set()
            self.ledger.set_metadata("emergency", False)
        elif action == "close_all_preview":
            token = secrets.token_urlsafe(24)
            pending = {
                "token": token,
                "expires_at": int(time.time()) + 90,
                "balances_hash": self._balances_hash(),
            }
            self.ledger.set_metadata("close_confirmation", pending)
            return {
                "confirmation": token,
                "expires_at": pending["expires_at"],
                "positions": self.view()["positions"],
                "mode": "paper",
                "requires_confirmation": True,
            }
        elif action == "close_all_confirm":
            previous = self.ledger.metadata("close_confirmation", {})
            if (
                not confirmation
                or not secrets.compare_digest(confirmation, previous.get("token", ""))
                or int(time.time()) > previous.get("expires_at", 0)
            ):
                raise ValueError("Close confirmation is invalid or expired; preview again")
            if previous["balances_hash"] != self._balances_hash():
                raise ValueError("Holdings changed after the preview; preview again")
            self.ledger.set_metadata("close_confirmation", {})
            self.halted.set()
            self.unwind = True
            self.running = True
        else:
            raise ValueError("Unsupported paper control")
        self.ledger.record(
            "control_changed", {"action": action, "mode": "paper", "paused": self.halted.is_set()}
        )
        return self.view()

    def _balances_hash(self):
        return hashlib.sha256(
            json.dumps(
                {a: str(r["amount_raw"]) for a, r in self.ledger.balances().items()}, sort_keys=True
            ).encode()
        ).hexdigest()
