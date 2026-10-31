# Why AEGIS is differentiated

**Autonomy with constrained authority and inspectable evidence.** AEGIS connects actual HSKSwap monitoring to deterministic, cost-aware signals, software risk checks, a single execution gate and persistent accounting. Its paper loop runs on live data and never fabricates a profitable trade to make a demo move.

| Pillar                             | Implemented evidence                                                                                          | Boundary                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Autonomous loop                    | Connected monitor → signal → risk → gateway → SQLite → dashboard; replayed entry/stop and rejected-risk tests | Paper profitability is unproven; no liquid mainnet triangle found                                  |
| Trade without withdrawal authority | Fixed vault recipient/router, owner-only exit, tighten-only caps, banded TWAP, independent triggered keeper   | 57 local contract checks and local fork execution; no independent audit or public AEGIS deployment |
| Verifiable decisions               | Earlier-block exact-byte action commitment, signed gateway reconciliation and exact reveal verification       | A byte commitment proves ordering/integrity, not truthful reasoning or profit                      |
| Human control                      | Shared typed tools, parameter diffs, out-of-range/injection refusals, confirmed close and latched panic       | Optional Claude/Telegram transports are implemented but real delivery requires credentials         |
| Honest demonstration               | Separate virtual fills, local fork hashes and public deployment registry; real dashboard/API interactions     | Missing deployment, credentials and funding remain visible                                         |

The next proof is a small funded public testnet run owned by the user's actual wallet, followed by longer cost-inclusive paper evaluation. Mainnet deployment or trading requires a separate explicit confirmation.
