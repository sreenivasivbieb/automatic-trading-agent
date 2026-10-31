// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {TickMath} from "./libraries/TickMath.sol";
import {IV3Pool, IV3Factory} from "./interfaces/IDex.sol";

/// @notice Values are settlement-token units, not independently verified USD.
/// The hot trading key has no authority to change anchors, bands or oracle markets.
contract BandedTwapOracle is Ownable {
    struct MarketConfig {
        address token;
        address pool;
        uint24 fee;
        uint128 anchorPriceX18;
        uint16 maxDeviationBps;
        uint32 windowSeconds;
    }

    struct Market {
        address pool;
        bytes32 poolCodeHash;
        bytes32 tokenCodeHash;
        uint128 anchorPriceX18;
        uint32 windowSeconds;
        uint16 maxDeviationBps;
        uint8 decimals;
    }

    address public immutable settlement;
    address public immutable factory;
    uint8 public immutable settlementDecimals;
    bytes32 public immutable settlementCodeHash;
    mapping(address => Market) public markets;
    address[] private _assets;

    error InvalidMarket();
    error UnsafeOracle();
    event MarketConfigured(
        address indexed token,
        address indexed pool,
        uint128 anchor,
        uint16 bandBps,
        uint32 windowSeconds
    );

    constructor(
        address initialOwner,
        address stable,
        address dexFactory,
        MarketConfig[] memory initialMarkets
    ) Ownable(initialOwner) {
        if (stable.code.length == 0 || dexFactory.code.length == 0) {
            revert InvalidMarket();
        }
        settlement = stable;
        factory = dexFactory;
        uint8 d = IERC20Metadata(stable).decimals();
        if (d > 18) revert InvalidMarket();
        settlementDecimals = d;
        settlementCodeHash = stable.codehash;
        _assets.push(stable);
        for (uint256 i; i < initialMarkets.length; ++i) {
            _configure(initialMarkets[i]);
        }
    }

    function configure(MarketConfig calldata config) external onlyOwner {
        _configure(config);
    }

    function _configure(MarketConfig memory c) internal {
        if (
            c.token == settlement || c.token.code.length == 0 || c.pool.code.length == 0
                || c.anchorPriceX18 == 0 || c.maxDeviationBps == 0 || c.maxDeviationBps > 2000
                || c.windowSeconds < 60 || c.windowSeconds > 1 days
        ) revert InvalidMarket();
        IV3Pool pool = IV3Pool(c.pool);
        if (
            pool.factory() != factory || pool.fee() != c.fee
                || IV3Factory(factory).getPool(c.token, settlement, c.fee) != c.pool
        ) revert InvalidMarket();
        if (!((pool.token0() == c.token && pool.token1() == settlement)
                    || (pool.token1() == c.token && pool.token0() == settlement))) revert InvalidMarket();
        uint8 d = IERC20Metadata(c.token).decimals();
        if (d > 18) revert InvalidMarket();
        if (markets[c.token].pool == address(0)) {
            if (_assets.length >= 8) revert InvalidMarket();
            _assets.push(c.token);
        }
        markets[c.token] = Market(
            c.pool,
            c.pool.codehash,
            c.token.codehash,
            c.anchorPriceX18,
            c.windowSeconds,
            c.maxDeviationBps,
            d
        );
        emit MarketConfigured(c.token, c.pool, c.anchorPriceX18, c.maxDeviationBps, c.windowSeconds);
    }

    function assets() external view returns (address[] memory) {
        return _assets;
    }

    function isAllowed(address token) public view returns (bool) {
        return token == settlement || markets[token].pool != address(0);
    }

    function decimals(address token) external view returns (uint8) {
        if (!isAllowed(token)) revert InvalidMarket();
        return token == settlement ? settlementDecimals : markets[token].decimals;
    }

    function price(address token) public view returns (uint256) {
        if (token == settlement) {
            if (
                token.codehash != settlementCodeHash
                    || IERC20Metadata(token).decimals() != settlementDecimals
            ) revert UnsafeOracle();
            return 1e18;
        }
        Market memory m = markets[token];
        if (
            m.pool == address(0) || m.pool.codehash != m.poolCodeHash
                || token.codehash != m.tokenCodeHash
                || IERC20Metadata(token).decimals() != m.decimals
        ) revert UnsafeOracle();
        uint32[] memory secondsAgos = new uint32[](2);
        secondsAgos[0] = m.windowSeconds;
        (int56[] memory cumulatives,) = IV3Pool(m.pool).observe(secondsAgos);
        if (cumulatives.length != 2) revert UnsafeOracle();
        int56 delta;
        unchecked {
            delta = cumulatives[1] - cumulatives[0];
        }
        int56 window = int56(uint56(m.windowSeconds));
        int24 tick = int24(delta / window);
        if (delta < 0 && delta % window != 0) --tick;
        // A million whole base tokens preserve precision for low-priced assets and six-decimal quotes.
        uint128 baseAmount = uint128(10 ** uint256(m.decimals) * 1_000_000);
        uint256 out = _quoteAtTick(tick, baseAmount, token, settlement);
        uint256 value = Math.mulDiv(out, 1e18, 10 ** uint256(settlementDecimals)) / 1_000_000;
        if (value == 0) revert UnsafeOracle();
        uint256 deviation =
            value > m.anchorPriceX18 ? value - m.anchorPriceX18 : m.anchorPriceX18 - value;
        if (Math.mulDiv(deviation, 10000, m.anchorPriceX18) > m.maxDeviationBps) {
            revert UnsafeOracle();
        }
        return value;
    }

    // The ratio branches follow Uniswap's OracleLibrary quote-at-tick method.
    function _quoteAtTick(int24 tick, uint128 baseAmount, address base, address quote)
        internal
        pure
        returns (uint256)
    {
        uint160 sqrtRatioX96 = TickMath.getSqrtRatioAtTick(tick);
        if (sqrtRatioX96 <= type(uint128).max) {
            uint256 ratioX192 = uint256(sqrtRatioX96) * sqrtRatioX96;
            return base < quote
                ? Math.mulDiv(ratioX192, baseAmount, 1 << 192)
                : Math.mulDiv(1 << 192, baseAmount, ratioX192);
        }
        uint256 ratioX128 = Math.mulDiv(sqrtRatioX96, sqrtRatioX96, 1 << 64);
        return base < quote
            ? Math.mulDiv(ratioX128, baseAmount, 1 << 128)
            : Math.mulDiv(1 << 128, baseAmount, ratioX128);
    }
}
