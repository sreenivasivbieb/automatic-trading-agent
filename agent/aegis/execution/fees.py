"""Pinned OP predeploy fee estimates. Price changes or unsupported operator tariffs fail closed."""

from __future__ import annotations

import json

from web3 import Web3

from aegis.connectors.rpc import DiscoveryError
from aegis.data import ROOT


class LiveFees:
    def __init__(self, rpc, chain_id: int):
        config = json.loads((ROOT / "config/fee-oracles.json").read_text())
        if config["schema_version"] != 1:
            raise DiscoveryError("Unknown fee registry schema")
        self.rpc, self.records = rpc, config["networks"][str(chain_id)]

    def estimate(self, *, gas: int, gas_price: int, transaction_bytes: int, block) -> int:
        for record in self.records.values():
            if (
                Web3.keccak(self.rpc.code(record["address"], block)).to_0x_hex().lower()
                != record["runtime_code_hash"].lower()
            ):
                raise DiscoveryError("Fee predeploy code changed; repeat fee discovery")
            actual = self.rpc.storage_address(
                record["address"], record["implementation_slot"], block
            )
            if (
                actual.lower() != record["implementation"].lower()
                or Web3.keccak(self.rpc.code(actual, block)).to_0x_hex().lower()
                != record["implementation_code_hash"].lower()
            ):
                raise DiscoveryError("Fee predeploy implementation changed; repeat fee discovery")
        attributes = self.records["l1_block"]["address"]
        scalar = self.rpc.call(attributes, "operatorFeeScalar()", ["uint32"], block)[0]
        constant = self.rpc.call(attributes, "operatorFeeConstant()", ["uint64"], block)[0]
        if scalar != 0 or constant != 0:
            raise DiscoveryError("Operator tariff differs from the verified zero-fee configuration")
        l1 = self.rpc.call(
            self.records["gas_oracle"]["address"],
            "getL1FeeUpperBound(uint256)",
            ["uint256"],
            block,
            types=["uint256"],
            args=[transaction_bytes + 256],
        )[0]
        # An estimate with a 2x buffer, not a promise about fees at future inclusion time.
        return 2 * (gas * gas_price + l1)
