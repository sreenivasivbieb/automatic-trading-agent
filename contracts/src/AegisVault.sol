// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeERC20, IERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {BandedTwapOracle} from "./BandedTwapOracle.sol";
import {DecisionLog} from "./DecisionLog.sol";
import {ISwapRouter02, IV3Factory, IWrappedNative} from "./interfaces/IDex.sol";

contract AegisVault is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct Limits {
        uint16 maxTradeBps;
        uint16 maxSlippageBps;
        uint16 maxTradesPerDay;
        uint16 dailyLossLimitBps;
        uint16 maxDrawdownBps;
        uint16 maxTokenExposureBps;
        uint16 maxTradesPerHour;
        uint16 stopLossBps;
        uint16 takeProfitBps;
        uint16 trailingStopBps;
        uint32 cooldownSeconds;
        uint32 maxHoldingSeconds;
        uint8 maxPositions;
    }

    address public agent;
    address public immutable router;
    bytes32 public immutable routerCodeHash;
    address public immutable wrappedNative;
    address public immutable settlement;
    BandedTwapOracle public immutable oracle;
    DecisionLog public immutable decisionLog;
    Limits public limits;
    bool public paused = true;
    uint256 public dayStartNav;
    uint256 public highWaterNav;
    uint256 public activeDay;
    uint256 public activeHour;
    uint256 public tradesToday;
    uint256 public tradesThisHour;
    uint256 public lastTradeAt;
    address[] private _assets;
    mapping(address => bool) public allowedTokens;
    mapping(address => bool) private _registered;
    mapping(address => uint256) public positionCost;
    mapping(address => uint256) public openedAt;
    mapping(address => uint256) public peakPrice;

    error Unauthorized();
    error Paused();
    error InvalidLimits();
    error InvalidRoute();
    error InvalidAmount();
    error InvalidDeadline();
    error TradeLimit();
    error UnsafeSlippage();
    error FrequencyLimit();
    error Cooldown();
    error ExposureLimit();
    error UnsupportedTransfer();
    error NativeTransferFailed();
    event Deposited(address indexed token, uint256 amount);
    event Withdrawn(address indexed token, address indexed owner, uint256 amount);
    event TokenAllowed(address indexed token, bool allowed);
    event PauseChanged(bool paused);
    event AgentChanged(address indexed agent);
    event LimitsTightened(Limits limits);
    event CircuitBreaker(bytes32 indexed reason, uint256 nav, uint256 referenceNav);
    event NavCheckpoint(
        uint256 indexed day, uint256 nav, uint256 dailyReference, uint256 highWater
    );
    event SwapExecuted(
        uint256 indexed decisionId,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        bytes32 pathHash,
        uint256 navBefore,
        uint256 navAfter
    );

    constructor(
        address initialOwner,
        address initialAgent,
        address dexRouter,
        address log,
        address priceOracle,
        address wrapped,
        Limits memory initialLimits
    ) Ownable(initialOwner) {
        if (
            initialAgent == address(0) || initialAgent == initialOwner || dexRouter.code.length == 0
                || log.code.length == 0 || priceOracle.code.length == 0 || wrapped.code.length == 0
        ) revert Unauthorized();
        oracle = BandedTwapOracle(priceOracle);
        decisionLog = DecisionLog(log);
        if (
            oracle.owner() != initialOwner || decisionLog.owner() != initialOwner
                || decisionLog.agent() != initialAgent
                || ISwapRouter02(dexRouter).factory() != oracle.factory()
                || ISwapRouter02(dexRouter).WETH9() != wrapped || !oracle.isAllowed(wrapped)
        ) revert InvalidRoute();
        agent = initialAgent;
        router = dexRouter;
        routerCodeHash = dexRouter.codehash;
        wrappedNative = wrapped;
        settlement = oracle.settlement();
        _validateLimits(initialLimits);
        limits = initialLimits;
        address[] memory assets_ = oracle.assets();
        for (uint256 i; i < assets_.length; ++i) {
            _assets.push(assets_[i]);
            _registered[assets_[i]] = true;
            allowedTokens[assets_[i]] = true;
            emit TokenAllowed(assets_[i], true);
        }
    }

    modifier onlyAgent() {
        if (msg.sender != agent) revert Unauthorized();
        _;
    }

    receive() external payable {
        if (msg.sender != owner() && msg.sender != wrappedNative) revert Unauthorized();
        _resetBaseline();
        emit Deposited(address(0), msg.value);
    }

    // A fixed owner keeps vault/log/oracle authority coherent. Exit and redeploy to migrate ownership.
    function transferOwnership(address) public view override onlyOwner {
        revert Unauthorized();
    }

    function renounceOwnership() public view override onlyOwner {
        revert Unauthorized();
    }

    function setAgent(address next) external onlyOwner {
        if (next == address(0) || next == owner()) revert Unauthorized();
        agent = next;
        emit AgentChanged(next);
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit PauseChanged(value);
    }

    function setTokenAllowed(address token, bool value) external onlyOwner {
        if (token == settlement || token == wrappedNative || !oracle.isAllowed(token)) {
            revert InvalidRoute();
        }
        if (!_registered[token]) {
            if (_assets.length >= 8) revert InvalidRoute();
            _assets.push(token);
            _registered[token] = true;
        }
        allowedTokens[token] = value;
        emit TokenAllowed(token, value);
    }

    function deposit(address token, uint256 amount) external nonReentrant onlyOwner {
        if (!allowedTokens[token] || amount == 0) revert InvalidAmount();
        uint256 beforeBalance = IERC20(token).balanceOf(address(this));
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        if (IERC20(token).balanceOf(address(this)) - beforeBalance != amount) {
            revert UnsupportedTransfer();
        }
        if (token != settlement) {
            uint256 p = oracle.price(token);
            positionCost[token] += Math.mulDiv(amount, p, 10 ** uint256(oracle.decimals(token)));
            if (beforeBalance == 0) openedAt[token] = block.timestamp;
            peakPrice[token] = p;
        }
        _resetBaseline();
        emit Deposited(token, amount);
    }

    function wrapNative(uint256 amount) external nonReentrant onlyOwner {
        if (amount == 0) revert InvalidAmount();
        IWrappedNative(wrappedNative).deposit{value: amount}();
        uint256 p = oracle.price(wrappedNative);
        positionCost[wrappedNative] += Math.mulDiv(amount, p, 1e18);
        if (openedAt[wrappedNative] == 0) openedAt[wrappedNative] = block.timestamp;
        peakPrice[wrappedNative] = p;
        emit Deposited(wrappedNative, amount);
    }

    /// @notice No recipient argument, no risk/oracle/pause dependency, owner only.
    function withdraw(address token, uint256 amount) external nonReentrant onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        if (amount == 0 || amount > balance) revert InvalidAmount();
        _reduceCost(token, amount, balance);
        IERC20(token).safeTransfer(owner(), amount);
        _resetBaseline();
        emit Withdrawn(token, owner(), amount);
    }

    function withdrawNative(uint256 amount) external nonReentrant onlyOwner {
        if (amount == 0 || amount > address(this).balance) revert InvalidAmount();
        (bool ok,) = payable(owner()).call{value: amount}("");
        if (!ok) revert NativeTransferFailed();
        _resetBaseline();
        emit Withdrawn(address(0), owner(), amount);
    }

    function _validateLimits(Limits memory l) internal pure {
        if (
            l.maxTradeBps == 0 || l.maxTradeBps > 3000 || l.maxSlippageBps == 0
                || l.maxSlippageBps > 500 || l.maxTradesPerDay == 0 || l.maxTradesPerDay > 100
                || l.maxTradesPerHour == 0 || l.maxTradesPerHour > l.maxTradesPerDay
                || l.dailyLossLimitBps == 0 || l.dailyLossLimitBps > 2000
                || l.maxDrawdownBps < l.dailyLossLimitBps || l.maxDrawdownBps > 5000
                || l.maxTokenExposureBps < l.maxTradeBps || l.maxTokenExposureBps > 5000
                || l.maxPositions == 0 || l.maxPositions > 7 || l.cooldownSeconds > 1 days
                || l.maxHoldingSeconds < 60 || l.maxHoldingSeconds > 7 days || l.stopLossBps == 0
                || l.stopLossBps > 5000 || l.takeProfitBps == 0 || l.takeProfitBps > 10000
                || l.trailingStopBps > l.stopLossBps
        ) revert InvalidLimits();
    }

    function tightenLimits(Limits calldata n) external onlyOwner {
        _validateLimits(n);
        Limits memory l = limits;
        if (
            n.maxTradeBps > l.maxTradeBps || n.maxSlippageBps > l.maxSlippageBps
                || n.maxTradesPerDay > l.maxTradesPerDay || n.maxTradesPerHour > l.maxTradesPerHour
                || n.dailyLossLimitBps > l.dailyLossLimitBps || n.maxDrawdownBps > l.maxDrawdownBps
                || n.maxTokenExposureBps > l.maxTokenExposureBps || n.maxPositions > l.maxPositions
                || n.cooldownSeconds < l.cooldownSeconds
                || n.maxHoldingSeconds > l.maxHoldingSeconds || n.stopLossBps > l.stopLossBps
                || n.takeProfitBps > l.takeProfitBps
                || (l.trailingStopBps != 0
                    && (n.trailingStopBps == 0 || n.trailingStopBps > l.trailingStopBps))
        ) revert InvalidLimits();
        limits = n;
        emit LimitsTightened(n);
    }

    function _resetBaseline() internal {
        dayStartNav = 0;
        highWaterNav = 0;
    }

    function nav() public view returns (uint256 value) {
        for (uint256 i; i < _assets.length; ++i) {
            address token = _assets[i];
            uint256 amount = IERC20(token).balanceOf(address(this));
            if (amount != 0) {
                value += Math.mulDiv(
                    amount, oracle.price(token), 10 ** uint256(oracle.decimals(token))
                );
            }
        }
        if (address(this).balance != 0) {
            value += Math.mulDiv(address(this).balance, oracle.price(wrappedNative), 1e18);
        }
    }

    function _trip(bytes32 reason, uint256 value, uint256 referenceValue) internal {
        paused = true;
        emit PauseChanged(true);
        emit CircuitBreaker(reason, value, referenceValue);
    }

    function _lossBreached(uint256 value) internal view returns (bool) {
        return value * 10000 < dayStartNav * (10000 - limits.dailyLossLimitBps)
            || value * 10000 < highWaterNav * (10000 - limits.maxDrawdownBps);
    }

    function _rollWindows(uint256 value) internal {
        uint256 day = block.timestamp / 1 days;
        uint256 hour = block.timestamp / 1 hours;
        if (day != activeDay) {
            activeDay = day;
            tradesToday = 0;
            dayStartNav = value;
        }
        if (hour != activeHour) {
            activeHour = hour;
            tradesThisHour = 0;
        }
        if (dayStartNav == 0) dayStartNav = value;
        if (value > highWaterNav) highWaterNav = value;
    }

    /// @notice Permissionless safety observation: can pause, never unpause or move funds.
    function checkpoint() external nonReentrant returns (uint256 value) {
        try this.nav() returns (uint256 current) {
            value = current;
            _rollWindows(value);
            if (_lossBreached(value) || _stopRequired()) {
                _trip("CHECKPOINT_STOP", value, dayStartNav);
            }
            emit NavCheckpoint(activeDay, value, dayStartNav, highWaterNav);
        } catch {
            _trip("CHECKPOINT_ORACLE", 0, dayStartNav);
        }
    }

    function _stopRequired() internal returns (bool) {
        for (uint256 i; i < _assets.length; ++i) {
            address token = _assets[i];
            uint256 cost = positionCost[token];
            uint256 balance = IERC20(token).balanceOf(address(this));
            if (token == settlement || balance == 0 || cost == 0) continue;
            uint256 p = oracle.price(token);
            if (p > peakPrice[token]) peakPrice[token] = p;
            uint256 value = Math.mulDiv(balance, p, 10 ** uint256(oracle.decimals(token)));
            if (
                value * 10000 < cost * (10000 - limits.stopLossBps)
                    || value * 10000 >= cost * (10000 + limits.takeProfitBps)
                    || block.timestamp > openedAt[token] + limits.maxHoldingSeconds
                    || (limits.trailingStopBps != 0
                        && p * 10000 < peakPrice[token] * (10000 - limits.trailingStopBps))
            ) return true;
        }
        return false;
    }

    function _tokenAt(bytes calldata path, uint256 offset) internal pure returns (address token) {
        assembly { token := shr(96, calldataload(add(path.offset, offset))) }
    }

    function _validatePath(bytes calldata path)
        internal
        view
        returns (address first, address last)
    {
        if (path.length < 43 || path.length > 89 || (path.length - 20) % 23 != 0) revert InvalidRoute();
        first = _tokenAt(path, 0);
        address current = first;
        address[3] memory seen;
        if (!allowedTokens[first]) revert InvalidRoute();
        uint256 hops = (path.length - 20) / 23;
        for (uint256 i; i < hops; ++i) {
            uint24 fee;
            uint256 offset = i * 23 + 20;
            assembly { fee := shr(232, calldataload(add(path.offset, offset))) }
            last = _tokenAt(path, i * 23 + 23);
            if (!allowedTokens[last] || current == last) revert InvalidRoute();
            address pool = IV3Factory(oracle.factory()).getPool(current, last, fee);
            if (pool == address(0) || pool.code.length == 0) revert InvalidRoute();
            for (uint256 j; j < i; ++j) {
                if (seen[j] == pool) revert InvalidRoute();
            }
            seen[i] = pool;
            current = last;
        }
    }

    function executionHash(
        bytes calldata path,
        uint256 amountIn,
        uint256 minimumOut,
        uint256 deadline
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(block.chainid, address(this), path, amountIn, minimumOut, deadline)
        );
    }

    function executeSwap(
        bytes calldata path,
        uint256 amountIn,
        uint256 minimumOut,
        uint256 deadline
    ) external nonReentrant onlyAgent returns (uint256 amountOut) {
        if (amountIn == 0 || minimumOut == 0) revert InvalidAmount();
        if (deadline <= block.timestamp || deadline > block.timestamp + 60) {
            revert InvalidDeadline();
        }
        if (router.codehash != routerCodeHash) revert InvalidRoute();
        (address tokenIn, address tokenOut) = _validatePath(path);
        bool exitOnly = tokenOut == settlement && tokenIn != settlement;
        if (paused && !exitOnly) revert Paused();
        uint256 beforeNav = 0;
        try this.nav() returns (uint256 value) {
            beforeNav = value;
        } catch {
            _trip("ORACLE_UNAVAILABLE", 0, dayStartNav);
            return 0;
        }
        _rollWindows(beforeNav);
        if (!exitOnly && (_lossBreached(beforeNav) || _stopRequired())) {
            _trip("LOSS_OR_POSITION_STOP", beforeNav, dayStartNav);
            return 0;
        }
        if (
            !exitOnly
                && (tradesToday >= limits.maxTradesPerDay
                    || tradesThisHour >= limits.maxTradesPerHour)
        ) revert FrequencyLimit();
        if (!exitOnly && lastTradeAt != 0 && block.timestamp < lastTradeAt + limits.cooldownSeconds)
        {
            revert Cooldown();
        }
        uint256 priceIn = oracle.price(tokenIn);
        uint256 priceOut = oracle.price(tokenOut);
        uint256 inputValue = Math.mulDiv(amountIn, priceIn, 10 ** uint256(oracle.decimals(tokenIn)));
        if (inputValue == 0 || inputValue * 10000 > beforeNav * limits.maxTradeBps) {
            revert TradeLimit();
        }
        uint256 referenceOut =
            Math.mulDiv(inputValue, 10 ** uint256(oracle.decimals(tokenOut)), priceOut);
        if (minimumOut < Math.mulDiv(referenceOut, 10000 - limits.maxSlippageBps, 10000)) {
            revert UnsafeSlippage();
        }
        uint256 beforeIn = IERC20(tokenIn).balanceOf(address(this));
        uint256 beforeOut = IERC20(tokenOut).balanceOf(address(this));
        if (amountIn > beforeIn) revert InvalidAmount();
        if (tokenOut != settlement) {
            uint256 projected = Math.mulDiv(
                beforeOut, priceOut, 10 ** uint256(oracle.decimals(tokenOut))
            ) + inputValue;
            if (projected * 10000 > beforeNav * limits.maxTokenExposureBps) revert ExposureLimit();
            uint256 countPositions = 0;
            for (uint256 i; i < _assets.length; ++i) {
                if (_assets[i] != settlement && IERC20(_assets[i]).balanceOf(address(this)) > 0) {
                    ++countPositions;
                }
            }
            if (tokenIn != settlement && beforeIn == amountIn) --countPositions;
            if (beforeOut == 0 && countPositions >= limits.maxPositions) revert ExposureLimit();
        }
        uint256 decisionId =
            decisionLog.consume(agent, executionHash(path, amountIn, minimumOut, deadline));
        IERC20(tokenIn).forceApprove(router, amountIn);
        uint256 reported = ISwapRouter02(router)
            .exactInput(ISwapRouter02.ExactInputParams(path, address(this), amountIn, minimumOut));
        IERC20(tokenIn).forceApprove(router, 0);
        uint256 afterIn = IERC20(tokenIn).balanceOf(address(this));
        uint256 afterOut = IERC20(tokenOut).balanceOf(address(this));
        if (tokenIn == tokenOut) {
            if (afterOut + amountIn < beforeOut) revert UnsupportedTransfer();
            amountOut = afterOut + amountIn - beforeOut;
        } else {
            if (beforeIn < afterIn || beforeIn - afterIn != amountIn || afterOut < beforeOut) {
                revert UnsupportedTransfer();
            }
            amountOut = afterOut - beforeOut;
        }
        if (amountOut < minimumOut || amountOut != reported) revert UnsupportedTransfer();
        if (tokenIn != settlement) _reduceCost(tokenIn, amountIn, beforeIn);
        if (tokenOut != settlement) {
            positionCost[tokenOut] += inputValue;
            if (beforeOut == 0) openedAt[tokenOut] = block.timestamp;
            peakPrice[tokenOut] = priceOut > peakPrice[tokenOut] ? priceOut : peakPrice[tokenOut];
        }
        ++tradesToday;
        ++tradesThisHour;
        lastTradeAt = block.timestamp;
        uint256 afterNav = 0;
        try this.nav() returns (uint256 value) {
            afterNav = value;
            if (_lossBreached(value)) _trip("POST_TRADE_LOSS", value, dayStartNav);
            if (value > highWaterNav) highWaterNav = value;
        } catch {
            _trip("POST_TRADE_ORACLE", 0, dayStartNav);
        }
        emit SwapExecuted(
            decisionId, tokenIn, tokenOut, amountIn, amountOut, keccak256(path), beforeNav, afterNav
        );
        emit NavCheckpoint(activeDay, afterNav, dayStartNav, highWaterNav);
    }

    function _reduceCost(address token, uint256 amount, uint256 balance) internal {
        if (amount == balance) {
            positionCost[token] = 0;
            openedAt[token] = 0;
            peakPrice[token] = 0;
        } else if (balance != 0) {
            positionCost[token] -= Math.mulDiv(positionCost[token], amount, balance);
        }
    }
}
