"""Read-only proof of the deployed Guard's size limit, separate from swap signing."""

from __future__ import annotations

from web3 import Web3
from web3.exceptions import ContractCustomError

from aegis.connectors.hskswap_v3 import encode_path


def prove_trade_limit(client, route) -> dict:
    """Require the *exact* TradeLimit selector; a timeout/other revert is not evidence."""
    block = client.verify()
    vault = client.vault
    oracle = client.records["BandedTwapOracle"]["address"]
    token = route.tokens[0]
    nav = vault.functions.nav().call(block_identifier=block.number)
    price = client.rpc.call(
        oracle,
        "price(address)",
        ["uint256"],
        block,
        types=["address"],
        args=[token.address],
    )[0]
    if nav <= 0 or price <= 0 or route.tokens[-1].asset_id != "USDT":
        raise ValueError("Risk proof requires a funded vault and a verified stable-exit route")
    # Deliberately exceed the entire NAV, so no allowed maxTradeBps can admit it.
    amount = ((nav + 1) * 10**token.decimals + price - 1) // price
    selector = Web3.keccak(text="TradeLimit()")[:4].to_0x_hex()
    function = vault.functions.executeSwap(encode_path(route), amount, 1, block.timestamp + 30)
    try:
        function.call({"from": client.account.address}, block_identifier=block.number)
    except ContractCustomError as exc:
        if getattr(exc, "data", None) != selector and selector not in exc.args:
            raise ValueError("Risk proof returned a different custom error") from None
    else:
        raise ValueError("Oversize eth_call was not rejected by the deployed Guard")
    client.rpc.assert_canonical(block)
    return {
        "status": "VERIFIED_ETH_CALL_REVERT",
        "method": "executeSwap",
        "error": "TradeLimit()",
        "selector": selector,
        "block_number": block.number,
        "block_hash": block.hash,
        "attempted_amount_raw": amount,
        "nav_x18": nav,
        "transaction_sent": False,
        "scope": "Canonical read-only execution of deployed bytecode; not a mined reverting transaction or a loss-circuit trigger.",
    }
