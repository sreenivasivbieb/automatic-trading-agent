# Third-party notices

This repository preserves and extends [vishal88736/alpaca-trading-agent](https://github.com/vishal88736/alpaca-trading-agent) at revision `2495276210d977dd09a5190def02755f5b96bea8`. That project is an enhanced Alpaca-oriented derivative of the [TauricResearch TradingAgents framework](https://github.com/TauricResearch/TradingAgents), with upstream contributions acknowledged in its preserved README.

The original Apache License 2.0 is retained in `LICENSE`. Original documentation, requirements and environment examples are preserved under `docs/upstream/`. Original package, Dash/CLI, prompts, numerical utilities, assets and tests remain in their documented paths. The three modified inherited files and the terminal's new implementation are described in `docs/ARCHITECTURE.md`.

React, TypeScript, Vite, Tailwind CSS, Lucide, FastAPI, Pydantic, LangGraph, pandas, Backtrader and other installed dependencies retain their respective licenses; their source is not vendored into the public repository's runtime cache.

Krono bundles Inter through Fontsource under the SIL Open Font License 1.1, included in the installed package. The current charcoal/lavender interface follows the user's supplied dashboard reference. Krono's monogram and terminal layouts are original implementation work. The decorative hero coin illustration was generated for this project with OpenAI's image-generation tool and is stored locally as an optimized transparent WebP.

cryptocurrency.cv is used through its hosted API. Its service source was not copied, redistributed or deployed. News records retain publisher attribution and original links. Synthetic fixture stories were authored for this demo and explicitly use non-real publisher URLs.

HSKChain network/token documentation and HSKSwap application resources were inspected for integration research. No third-party HSKSwap application bundle or unverified router implementation is published in this repository. The terminal logo and interface do not claim endorsement by an exchange or hackathon organizer.

AEGIS vendors the selected OpenZeppelin Contracts 5.0.2 files listed in [contracts/DEPENDENCIES.json](contracts/DEPENDENCIES.json), under the included [MIT license](contracts/lib/openzeppelin/LICENSE). It also adapts `TickMath.getSqrtRatioAtTick` from the official `@uniswap/v3-core` 1.0.1 package, retaining its GPL-2.0-or-later notice and [license text](contracts/src/libraries/LICENSE_GPL). The compiler compatibility and formatting changes are recorded in the manifest. The AEGIS vault/oracle, deployment script and contract tests that incorporate that library carry GPL-2.0-or-later notices; DecisionLog and standalone DEX interfaces carry MIT notices. These contract-specific notices are additional to the inherited framework's Apache-2.0 license.
