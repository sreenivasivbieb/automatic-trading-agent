// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity ^0.8.24;

import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {BandedTwapOracle} from "../src/BandedTwapOracle.sol";
import {DecisionLog} from "../src/DecisionLog.sol";
import {AegisVault} from "../src/AegisVault.sol";
import {TestBase} from "./Helpers.sol";

interface IRealSlot0 {
    function slot0() external view returns (uint160, int24, uint16, uint16, uint16, uint8, bool);
}

contract OracleQuoteHarness is BandedTwapOracle {
    constructor(address stable, address factory_)
        BandedTwapOracle(msg.sender, stable, factory_, new MarketConfig[](0))
    {}

    function rawQuote(int24 tick, uint128 amount, address base, address quote)
        external
        pure
        returns (uint256)
    {
        return _quoteAtTick(tick, amount, base, quote);
    }
}

/// @notice Optional integration test: local fork state only; never broadcasts to HashKey.
contract LiveForkTest is TestBase {
    event ForkProof(
        uint256 chainId, uint256 forkBlock, uint256 amountIn, uint256 minimumOut, uint256 amountOut
    );

    function testRealRouterGuardedStableExitOnLocalFork() public {
        if (!vm.envOr("AEGIS_LIVE_ORACLE_TESTS", false)) {
            vm.skip(true);
            return;
        }
        require(block.chainid == 133 || block.chainid == 177, "choose a verified HashKey fork");
        uint256 forkBlock = block.number;
        // Addresses are copied from config/networks.yaml, verified in docs/discovery/contracts.json.
        address stable;
        address wrapped;
        address factory_;
        address router_;
        address pool;
        if (block.chainid == 133) {
            stable = 0x98B6173A8B7DFc52ce8bc88f1184a918A1CCaa4F;
            wrapped = 0xCA8aAceEC5Db1e91B9Ed3a344bA026c4a2B3ebF6;
            factory_ = 0x2dC2c21D1049F786C535bF9d45F999dB5474f3A0;
            router_ = 0xa6914E66690c6794244B5f66a09eAEbf66254237;
            pool = 0xc076FB478b77633736738579c7f48D2539604a50;
        } else {
            stable = 0xF1B50eD67A9e2CC94Ad3c477779E2d4cBfFf9029;
            wrapped = 0xB210D2120d57b758EE163cFfb43e73728c471Cf1;
            factory_ = 0x972cA9D1662F5e029cD18327D29026532E84c742;
            router_ = 0x2c16f75b95Cf1390c328aB70e2CEE7f4b80bD8F3;
            pool = 0x4ff515761864e7838B0AdB8b5b2B8B7A068905dC;
        }
        require(IERC20Metadata(wrapped).decimals() == 18, "wrapped native decimals");
        uint8 stableDecimals = IERC20Metadata(stable).decimals();
        OracleQuoteHarness quoteHelper = new OracleQuoteHarness(stable, factory_);
        (, int24 tick,,,,,) = IRealSlot0(pool).slot0();
        uint256 raw = quoteHelper.rawQuote(tick, 1e24, wrapped, stable);
        uint256 anchor = Math.mulDiv(raw, 1e18, 10 ** uint256(stableDecimals)) / 1_000_000;
        require(anchor > 0 && anchor < type(uint128).max, "anchor range");
        BandedTwapOracle.MarketConfig[] memory markets = new BandedTwapOracle.MarketConfig[](1);
        markets[0] = BandedTwapOracle.MarketConfig(wrapped, pool, 3000, uint128(anchor), 2000, 60);
        BandedTwapOracle oracle = new BandedTwapOracle(address(this), stable, factory_, markets);
        address localAgent = address(0xB0B); // Synthetic local-fork caller, never a deployment owner.
        DecisionLog log = new DecisionLog(address(this), localAgent);
        AegisVault.Limits memory caps =
            AegisVault.Limits(1000, 100, 20, 200, 1000, 3000, 6, 1000, 1500, 0, 30, 3600, 3);
        AegisVault vault = new AegisVault(
            address(this), localAgent, router_, address(log), address(oracle), wrapped, caps
        );
        log.bindVault(address(vault));
        vm.deal(address(this), 1 ether);
        (bool ok,) = address(vault).call{value: 0.1 ether}("");
        require(ok, "local native deposit");
        vault.wrapNative(0.1 ether);
        uint256 amount = 0.01 ether;
        uint256 value = Math.mulDiv(amount, oracle.price(wrapped), 1e18);
        uint256 minimum = Math.mulDiv(value, 10 ** uint256(stableDecimals), 1e18) * 99 / 100;
        require(minimum > 0, "minimum rounds to zero");
        bytes memory path = abi.encodePacked(wrapped, uint24(3000), stable);
        uint256 deadline = block.timestamp + 30;
        bytes memory decision =
            bytes('{"mode":"local_fork","reason":"bounded stable exit integration proof"}');
        bytes32 execution = vault.executionHash(path, amount, minimum, deadline);
        vm.prank(localAgent);
        uint256 id = log.commit(keccak256(decision), execution);
        vm.roll(block.number + 1);
        vm.prank(localAgent);
        uint256 output = vault.executeSwap(path, amount, minimum, deadline);
        require(output >= minimum, "real router minimum");
        eq(IERC20Metadata(stable).balanceOf(address(vault)), output);
        eq(IERC20Metadata(stable).balanceOf(localAgent), 0);
        eq(IERC20Metadata(wrapped).allowance(address(vault), router_), 0);
        vm.prank(localAgent);
        log.reveal(id, decision);
        emit ForkProof(block.chainid, forkBlock, amount, minimum, output);
    }
}
