// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AegisVault} from "../src/AegisVault.sol";
import {BandedTwapOracle} from "../src/BandedTwapOracle.sol";
import {DecisionLog} from "../src/DecisionLog.sol";
import {
    MockToken,
    MockPool,
    MockFactory,
    MockRouter,
    TestBase,
    Vm,
    IReentryCallback
} from "./Helpers.sol";

contract AgentCallback is IReentryCallback {
    AegisVault public vault;
    DecisionLog public log;
    bool public blocked;

    constructor(AegisVault v, DecisionLog l) {
        vault = v;
        log = l;
    }

    function commit(bytes32 d, bytes32 e) external {
        log.commit(d, e);
    }

    function run(bytes calldata path, uint256 amount, uint256 minimum, uint256 deadline) external {
        vault.executeSwap(path, amount, minimum, deadline);
    }

    function onSwap(bytes calldata path, uint256 amount, uint256 minimum) external {
        (bool ok, bytes memory reason) = address(vault)
            .call(
                abi.encodeCall(
                    AegisVault.executeSwap, (path, amount, minimum, block.timestamp + 30)
                )
            );
        require(
            !ok && bytes4(reason) == ReentrancyGuard.ReentrancyGuardReentrantCall.selector,
            "reentry accepted"
        );
        blocked = true;
    }
}

contract VaultTest is TestBase {
    // Synthetic addresses for local EVM tests, never deployment configuration.
    address internal owner = address(0xA11CE);
    address internal agent = address(0xB0B);
    address internal outsider = address(0xBAD);
    MockToken internal stable;
    MockToken internal asset;
    MockToken internal asset2;
    MockPool internal pool;
    MockPool internal pool2;
    MockFactory internal factory;
    MockRouter internal router;
    BandedTwapOracle internal oracle;
    DecisionLog internal log;
    AegisVault internal vault;
    bytes internal payload = bytes('{"mode":"local_evm_test","reason":"pretrade fixture"}');

    function defaultLimits() internal pure returns (AegisVault.Limits memory) {
        return AegisVault.Limits(1000, 100, 20, 200, 1000, 3000, 6, 1000, 1500, 0, 30, 3600, 3);
    }

    function setUp() public {
        vm.warp(1_000_000);
        vm.roll(100);
        stable = new MockToken("USDT", 18);
        asset = new MockToken("WHSK", 18);
        asset2 = new MockToken("WETH", 18);
        factory = new MockFactory();
        pool = new MockPool(address(factory), address(asset), address(stable), 3000);
        pool2 = new MockPool(address(factory), address(asset2), address(stable), 3000);
        factory.setPool(address(asset), address(stable), 3000, address(pool));
        factory.setPool(address(asset2), address(stable), 3000, address(pool2));
        BandedTwapOracle.MarketConfig[] memory markets = new BandedTwapOracle.MarketConfig[](2);
        markets[0] =
            BandedTwapOracle.MarketConfig(address(asset), address(pool), 3000, 1e18, 2000, 60);
        markets[1] =
            BandedTwapOracle.MarketConfig(address(asset2), address(pool2), 3000, 1e18, 2000, 60);
        oracle = new BandedTwapOracle(owner, address(stable), address(factory), markets);
        log = new DecisionLog(owner, agent);
        router = new MockRouter(address(factory), address(asset));
        vault = new AegisVault(
            owner,
            agent,
            address(router),
            address(log),
            address(oracle),
            address(asset),
            defaultLimits()
        );
        log.bindVault(address(vault));
        stable.mint(owner, 1000 ether);
        asset.mint(address(router), 10000 ether);
        asset2.mint(address(router), 10000 ether);
        stable.mint(address(router), 10000 ether);
        vm.startPrank(owner);
        stable.approve(address(vault), type(uint256).max);
        vault.deposit(address(stable), 1000 ether);
        vault.setPaused(false);
        vm.stopPrank();
    }

    function path(address a, address b) internal pure returns (bytes memory) {
        return abi.encodePacked(a, uint24(3000), b);
    }

    function commitSwap(bytes memory p, uint256 amount, uint256 minimum, uint256 deadline)
        internal
        returns (uint256 id)
    {
        bytes32 action = vault.executionHash(p, amount, minimum, deadline);
        vm.prank(agent);
        id = log.commit(keccak256(payload), action);
        vm.roll(block.number + 1);
    }

    function buy() internal returns (uint256 out) {
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 100 ether, 99 ether, deadline);
        vm.prank(agent);
        out = vault.executeSwap(p, 100 ether, 99 ether, deadline);
    }

    function setRelativeTick(int24 tick) internal {
        pool.setTick(address(asset) < address(stable) ? tick : -tick);
    }

    function keeperCommit(bytes memory p, uint256 amount, uint256 minimum, uint256 deadline)
        internal
        returns (uint256 id)
    {
        bytes32 action = vault.keeperExecutionHash(p, amount, minimum, deadline);
        vm.prank(outsider);
        id = log.commitKeeper(keccak256(payload), action);
        vm.roll(block.number + 1);
    }

    function testIndependentKeeperExecutesStopWithoutAgentOrCallerPayout() public {
        buy();
        setRelativeTick(-1200);
        require(vault.keeperStatus(address(asset)) == bytes32("STOP_LOSS"), "stop trigger");
        bytes memory p = path(address(asset), address(stable));
        uint256 amount = asset.balanceOf(address(vault));
        uint256 minimum = amount * oracle.price(address(asset)) / 1e18 * 99 / 100;
        uint256 deadline = block.timestamp + 30;
        uint256 id = keeperCommit(p, amount, minimum, deadline);
        uint256 beforeBalance = stable.balanceOf(address(vault));
        vm.prank(outsider);
        uint256 out = vault.keeperClose(p, amount, minimum, deadline);
        require(out >= minimum, "keeper floor");
        eq(stable.balanceOf(address(vault)), beforeBalance + out);
        eq(stable.balanceOf(outsider), 0);
        eq(asset.balanceOf(outsider), 0);
        eq(asset.allowance(address(vault), address(router)), 0);
        require(vault.paused(), "keeper latches entry pause");
        vm.prank(outsider);
        log.reveal(id, payload);
    }

    function testKeeperCannotCloseUntriggeredPosition() public {
        buy();
        bytes memory p = path(address(asset), address(stable));
        vm.expectRevert(AegisVault.NotTriggered.selector);
        vm.prank(outsider);
        vault.keeperClose(p, 10 ether, 9.9 ether, block.timestamp + 30);
    }

    function testKeeperDeadManWorksAfterAgentSilence() public {
        buy();
        vm.warp(block.timestamp + 3601);
        require(vault.keeperStatus(address(asset)) == bytes32("DEAD_MAN"), "dead man trigger");
        bytes memory p = path(address(asset), address(stable));
        uint256 deadline = block.timestamp + 30;
        keeperCommit(p, 50 ether, 49.5 ether, deadline);
        uint256 heartbeatBefore = vault.lastHeartbeat();
        vm.prank(outsider);
        vault.keeperClose(p, 50 ether, 49.5 ether, deadline);
        eq(vault.lastHeartbeat(), heartbeatBefore);
        require(vault.paused(), "dead man pause");
    }

    function testHeartbeatCannotBeSentByKeeperOrLoosenTimeout() public {
        vm.expectRevert(AegisVault.Unauthorized.selector);
        vm.prank(outsider);
        vault.heartbeat();
        vm.prank(owner);
        vault.tightenHeartbeatTimeout(300);
        vm.expectRevert(AegisVault.InvalidLimits.selector);
        vm.prank(owner);
        vault.tightenHeartbeatTimeout(301);
        vm.warp(block.timestamp + 301);
        vm.prank(agent);
        vault.heartbeat();
        eq(vault.lastHeartbeat(), block.timestamp);
    }

    function testKeeperMustCommitInEarlierBlock() public {
        buy();
        vm.warp(block.timestamp + 3601);
        bytes memory p = path(address(asset), address(stable));
        uint256 deadline = block.timestamp + 30;
        bytes32 action = vault.keeperExecutionHash(p, 50 ether, 49.5 ether, deadline);
        vm.prank(outsider);
        log.commitKeeper(keccak256(payload), action);
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(outsider);
        vault.keeperClose(p, 50 ether, 49.5 ether, deadline);
    }

    function testKeeperCommitCannotAuthorizeAnAgentEntry() public {
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        bytes32 action = vault.executionHash(p, 50 ether, 49.5 ether, deadline);
        vm.prank(agent);
        log.commitKeeper(keccak256(payload), action);
        vm.roll(block.number + 1);
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(agent);
        vault.executeSwap(p, 50 ether, 49.5 ether, deadline);
        eq(stable.balanceOf(address(vault)), 1000 ether);
    }

    function testKeeperCannotUseEntryRouteOrExceedTradeCap() public {
        bytes memory wrong = path(address(stable), address(asset));
        vm.expectRevert(AegisVault.InvalidRoute.selector);
        vm.prank(outsider);
        vault.keeperClose(wrong, 10 ether, 9.9 ether, block.timestamp + 30);
        buy();
        uint256 advancedTime = block.timestamp + 3601;
        vm.warp(advancedTime);
        AegisVault.Limits memory caps = defaultLimits();
        caps.maxTradeBps = 100;
        vm.prank(owner);
        vault.tightenLimits(caps);
        bytes memory p = path(address(asset), address(stable));
        vm.expectRevert(AegisVault.TradeLimit.selector);
        vm.prank(outsider);
        vault.keeperClose(p, 50 ether, 49.5 ether, vm.getBlockTimestamp() + 30);
    }

    function testAgentCannotWithdrawERC20() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vm.prank(agent);
        vault.withdraw(address(stable), 1 ether);
        eq(stable.balanceOf(address(vault)), 1000 ether);
        eq(stable.balanceOf(agent), 0);
    }

    function testAgentCannotWithdrawNative() public {
        vm.deal(address(vault), 1 ether);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vm.prank(agent);
        vault.withdrawNative(1 ether);
        eq(address(vault).balance, 1 ether);
    }

    function testOutsiderCannotExecute() public {
        vm.expectRevert(AegisVault.Unauthorized.selector);
        vm.prank(outsider);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 1 ether, block.timestamp + 30
        );
    }

    function testSwapRecipientIsVaultAndApprovalCleared() public {
        uint256 out = buy();
        eq(out, 99.7 ether);
        eq(router.lastRecipient(), address(vault));
        eq(asset.balanceOf(agent), 0);
        eq(asset.balanceOf(owner), 0);
        eq(asset.balanceOf(address(vault)), out);
        eq(stable.allowance(address(vault), address(router)), 0);
    }

    function testCannotTradeUnknownToken() public {
        MockToken unknown = new MockToken("UNKNOWN", 18);
        vm.expectRevert(AegisVault.InvalidRoute.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(unknown)), 1 ether, 1 ether, block.timestamp + 30
        );
    }

    function testCannotUseNonFactoryPoolFee() public {
        bytes memory bad = abi.encodePacked(address(stable), uint24(10000), address(asset));
        vm.expectRevert(AegisVault.InvalidRoute.selector);
        vm.prank(agent);
        vault.executeSwap(bad, 1 ether, 1 ether, block.timestamp + 30);
    }

    function testWrongRouterFactoryRejectedAtConstruction() public {
        MockFactory wrongFactory = new MockFactory();
        MockRouter bad = new MockRouter(address(wrongFactory), address(asset));
        vm.expectRevert(AegisVault.InvalidRoute.selector);
        new AegisVault(
            owner,
            agent,
            address(bad),
            address(log),
            address(oracle),
            address(asset),
            defaultLimits()
        );
    }

    function testAgentCannotCallArbitraryRouter() public {
        vm.prank(agent);
        (bool ok,) = address(vault)
            .call(abi.encodeWithSignature("execute(address,bytes)", outsider, hex"1234"));
        require(!ok, "arbitrary call accepted");
    }

    function testAgentCannotRaiseOrTightenCaps() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxTradeBps = 500;
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vm.prank(agent);
        vault.tightenLimits(next);
    }

    function testOwnerCanOnlyTightenCaps() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxTradeBps = 500;
        vm.prank(owner);
        vault.tightenLimits(next);
        next.maxTradeBps = 1000;
        vm.expectRevert(AegisVault.InvalidLimits.selector);
        vm.prank(owner);
        vault.tightenLimits(next);
    }

    function testTradeSizeBreachRevertsBeforeRouter() public {
        vm.expectRevert(AegisVault.TradeLimit.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 101 ether, 100 ether, block.timestamp + 30
        );
        eq(stable.balanceOf(address(vault)), 1000 ether);
    }

    function testSlippageFloorCannotBeChosenArbitrarilyLow() public {
        vm.expectRevert(AegisVault.UnsafeSlippage.selector);
        vm.prank(agent);
        vault.executeSwap(path(address(stable), address(asset)), 100 ether, 1, block.timestamp + 30);
    }

    function testExpiredAndOverlongDeadlinesRevert() public {
        vm.expectRevert(AegisVault.InvalidDeadline.selector);
        vm.prank(agent);
        vault.executeSwap(path(address(stable), address(asset)), 1 ether, 1 ether, block.timestamp);
        vm.expectRevert(AegisVault.InvalidDeadline.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 1 ether, block.timestamp + 61
        );
    }

    function testZeroAmountCannotTriggerRouterEntireBalanceMode() public {
        vm.expectRevert(AegisVault.InvalidAmount.selector);
        vm.prank(agent);
        vault.executeSwap(path(address(stable), address(asset)), 0, 1, block.timestamp + 30);
    }

    function testCooldownReverts() public {
        buy();
        vm.expectRevert(AegisVault.Cooldown.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testDayAndHourFrequencyCaps() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxTradesPerDay = 1;
        next.maxTradesPerHour = 1;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        vm.warp(block.timestamp + 31);
        vm.expectRevert(AegisVault.FrequencyLimit.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testTokenExposureCap() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxTokenExposureBps = 1000;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        vm.warp(block.timestamp + 31);
        vm.expectRevert(AegisVault.ExposureLimit.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testDailyLossCircuitPersistsWithoutReverting() public {
        buy();
        stable.burn(address(vault), 25 ether);
        vm.warp(block.timestamp + 31);
        uint256 beforeBalance = stable.balanceOf(address(vault));
        vm.prank(agent);
        uint256 out = vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
        eq(out, 0);
        require(vault.paused(), "circuit did not persist");
        eq(stable.balanceOf(address(vault)), beforeBalance);
    }

    function testPostTradeCircuitPersists() public {
        AegisVault.Limits memory next = defaultLimits();
        next.dailyLossLimitBps = 1;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        require(vault.paused(), "post-trade loss not latched");
    }

    function testPositionStopLossBlocksNewEntries() public {
        buy();
        setRelativeTick(-1200);
        vm.warp(block.timestamp + 31);
        vm.prank(agent);
        uint256 out = vault.executeSwap(
            path(address(stable), address(asset2)), 1 ether, 0.99 ether, block.timestamp + 30
        );
        eq(out, 0);
        require(vault.paused(), "position stop not latched");
    }

    function testTimeStopBlocksNewEntries() public {
        buy();
        vm.warp(block.timestamp + 3601);
        vm.prank(agent);
        uint256 out = vault.executeSwap(
            path(address(stable), address(asset2)), 1 ether, 0.99 ether, block.timestamp + 30
        );
        eq(out, 0);
        require(vault.paused(), "time stop not latched");
    }

    function testPausedVaultRefusesNewEntries() public {
        vm.prank(owner);
        vault.setPaused(true);
        vm.expectRevert(AegisVault.Paused.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testBoundedStableExitStillAvailableWhilePaused() public {
        buy();
        vm.prank(owner);
        vault.setPaused(true);
        bytes memory p = path(address(asset), address(stable));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 10 ether, 9.9 ether, deadline);
        vm.prank(agent);
        uint256 out = vault.executeSwap(p, 10 ether, 9.9 ether, deadline);
        eq(out, 9.97 ether);
        require(vault.paused(), "exit unpaused entries");
    }

    function testOwnerCanExitWhilePausedAndOracleBroken() public {
        buy();
        pool.setBroken(true);
        vm.prank(owner);
        vault.setPaused(true);
        uint256 stableBalance = stable.balanceOf(address(vault));
        uint256 assetBalance = asset.balanceOf(address(vault));
        vm.startPrank(owner);
        vault.withdraw(address(stable), stableBalance);
        vault.withdraw(address(asset), assetBalance);
        vm.stopPrank();
        eq(stable.balanceOf(owner), stableBalance);
        eq(asset.balanceOf(owner), assetBalance);
    }

    function testOwnerCanAlwaysExitNativeWhilePaused() public {
        vm.deal(address(vault), 1 ether);
        vm.prank(owner);
        vault.setPaused(true);
        vm.prank(owner);
        vault.withdrawNative(1 ether);
        eq(owner.balance, 1 ether);
        eq(address(vault).balance, 0);
    }

    function testOracleFailureAutoPausesWhenPositionHeld() public {
        buy();
        pool.setBroken(true);
        vm.warp(block.timestamp + 31);
        vm.prank(agent);
        uint256 out = vault.executeSwap(
            path(address(stable), address(asset2)), 1 ether, 0.99 ether, block.timestamp + 30
        );
        eq(out, 0);
        require(vault.paused(), "oracle failure not latched");
    }

    function testAgentCannotWalkOracleAnchor() public {
        BandedTwapOracle.MarketConfig memory next =
            BandedTwapOracle.MarketConfig(address(asset), address(pool), 3000, 2e18, 2000, 60);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vm.prank(agent);
        oracle.configure(next);
        setRelativeTick(-3000);
        vm.expectRevert(BandedTwapOracle.UnsafeOracle.selector);
        oracle.price(address(asset));
    }

    function testOutputTransferTaxAndMisreportRevertAtomically() public {
        asset.setFee(100);
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 100 ether, 99 ether, deadline);
        vm.expectRevert(AegisVault.UnsupportedTransfer.selector);
        vm.prank(agent);
        vault.executeSwap(p, 100 ether, 99 ether, deadline);
        eq(stable.balanceOf(address(vault)), 1000 ether);
        eq(asset.balanceOf(address(vault)), 0);
    }

    function testFeeOnTransferDepositRejected() public {
        asset.mint(owner, 10 ether);
        asset.setFee(100);
        vm.prank(owner);
        asset.approve(address(vault), 10 ether);
        vm.expectRevert(AegisVault.UnsupportedTransfer.selector);
        vm.prank(owner);
        vault.deposit(address(asset), 10 ether);
        eq(asset.balanceOf(owner), 10 ether);
    }

    function testExecuteRequiresPriorBoundCommit() public {
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 100 ether, 99 ether, block.timestamp + 30
        );
    }

    function testCommitBindsAmountRouteMinimumDeadlineAndVault() public {
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 100 ether, 99 ether, deadline);
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(agent);
        vault.executeSwap(p, 99 ether, 99 ether, deadline);
    }

    function testSameBlockCommitCannotExecute() public {
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        bytes32 action = vault.executionHash(p, 100 ether, 99 ether, deadline);
        vm.prank(agent);
        log.commit(keccak256(payload), action);
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(agent);
        vault.executeSwap(p, 100 ether, 99 ether, deadline);
    }

    function testCommitExecuteRevealOrderingAndReplayProtection() public {
        vm.recordLogs();
        buy();
        vm.prank(agent);
        log.reveal(1, payload);
        Vm.Log[] memory events = vm.getRecordedLogs();
        uint256 committed;
        uint256 consumed;
        uint256 swapped;
        uint256 revealed;
        for (uint256 i; i < events.length; ++i) {
            bytes32 topic = events[i].topics[0];
            if (topic == keccak256("Committed(uint256,address,bytes32,bytes32,uint256)")) {
                committed = i + 1;
            }
            if (topic == keccak256("Consumed(uint256,bytes32,uint256)")) consumed = i + 1;
            if (
                topic
                    == keccak256(
                        "SwapExecuted(uint256,address,address,uint256,uint256,bytes32,uint256,uint256)"
                    )
            ) swapped = i + 1;
            if (topic == keccak256("Revealed(uint256,bytes,uint256)")) revealed = i + 1;
        }
        require(
            committed > 0 && committed < consumed && consumed < swapped && swapped < revealed,
            "event ordering"
        );
        vm.expectRevert(DecisionLog.InvalidReveal.selector);
        vm.prank(agent);
        log.reveal(1, payload);
    }

    function testBadRevealAndOverwriteRefused() public {
        vm.prank(agent);
        log.commit(keccak256(payload));
        vm.expectRevert(DecisionLog.PendingDecision.selector);
        vm.prank(agent);
        log.commit(keccak256(payload));
        vm.expectRevert(DecisionLog.InvalidReveal.selector);
        vm.prank(agent);
        log.reveal(1, bytes("wrong"));
        vm.expectRevert(DecisionLog.InvalidReveal.selector);
        vm.prank(outsider);
        log.reveal(1, payload);
        vm.prank(agent);
        log.reveal(1, payload);
        eq(log.pending(agent), 0);
    }

    function testLogVaultBindingCannotBeChanged() public {
        vm.expectRevert(DecisionLog.Unauthorized.selector);
        vm.prank(owner);
        log.bindVault(address(router));
    }

    function testAuthorizedReentrancyIsBlocked() public {
        AgentCallback callback = new AgentCallback(vault, log);
        vm.startPrank(owner);
        vault.setAgent(address(callback));
        log.setAgent(address(callback));
        vm.stopPrank();
        router.setCallback(address(callback));
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        callback.commit(keccak256(payload), vault.executionHash(p, 100 ether, 99 ether, deadline));
        vm.roll(block.number + 1);
        callback.run(p, 100 ether, 99 ether, deadline);
        require(callback.blocked(), "guard not exercised");
    }

    function testFuzzAgentCannotWithdraw(uint256 rawAmount) public {
        uint256 amount = 1 + rawAmount % (1000 ether);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vm.prank(agent);
        vault.withdraw(address(stable), amount);
    }

    function testFuzzCapBreachNeverSpends(uint256 extra) public {
        uint256 amount = 101 ether + extra % (800 ether);
        vm.expectRevert(AegisVault.TradeLimit.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), amount, amount, block.timestamp + 30
        );
        eq(stable.balanceOf(address(vault)), 1000 ether);
    }

    function testMaxConcurrentPositions() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxPositions = 1;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        vm.warp(block.timestamp + 31);
        vm.expectRevert(AegisVault.ExposureLimit.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset2)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testHourlyCounterResets() public {
        AegisVault.Limits memory next = defaultLimits();
        next.maxTradesPerDay = 2;
        next.maxTradesPerHour = 1;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        vm.warp((block.timestamp / 1 hours + 1) * 1 hours + 1);
        bytes memory p = path(address(stable), address(asset2));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 1 ether, 0.99 ether, deadline);
        vm.prank(agent);
        vault.executeSwap(p, 1 ether, 0.99 ether, deadline);
        eq(vault.tradesToday(), 2);
        eq(vault.tradesThisHour(), 1);
    }

    function testTakeProfitBlocksAdditionalEntries() public {
        buy();
        setRelativeTick(1500);
        vm.warp(block.timestamp + 31);
        vm.prank(agent);
        uint256 out = vault.executeSwap(
            path(address(stable), address(asset2)), 1 ether, 0.99 ether, block.timestamp + 30
        );
        eq(out, 0);
        require(vault.paused(), "take profit not latched");
    }

    function testTrailingStopTracksPeak() public {
        AegisVault.Limits memory next = defaultLimits();
        next.trailingStopBps = 500;
        vm.prank(owner);
        vault.tightenLimits(next);
        buy();
        setRelativeTick(1000);
        vm.warp(block.timestamp + 31);
        bytes memory p = path(address(stable), address(asset2));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 1 ether, 0.99 ether, deadline);
        vm.prank(agent);
        vault.executeSwap(p, 1 ether, 0.99 ether, deadline);
        setRelativeTick(400);
        vm.warp(block.timestamp + 31);
        vm.prank(agent);
        uint256 out = vault.executeSwap(p, 1 ether, 0.99 ether, block.timestamp + 30);
        eq(out, 0);
        require(vault.paused(), "trailing stop not latched");
    }

    function testRouterMisreportRollsBack() public {
        router.setBadReport(true);
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 100 ether, 99 ether, deadline);
        vm.expectRevert(AegisVault.UnsupportedTransfer.selector);
        vm.prank(agent);
        vault.executeSwap(p, 100 ether, 99 ether, deadline);
        eq(stable.balanceOf(address(vault)), 1000 ether);
    }

    function testRouterCodeChangeRefused() public {
        vm.etch(address(router), hex"00");
        vm.expectRevert(AegisVault.InvalidRoute.selector);
        vm.prank(agent);
        vault.executeSwap(
            path(address(stable), address(asset)), 1 ether, 0.99 ether, block.timestamp + 30
        );
    }

    function testNegativeTwapRemainderRoundsDown() public {
        pool.setRemainder(-1);
        uint256 p = oracle.price(address(asset));
        require(
            address(asset) < address(stable) ? p < 1e18 : p > 1e18,
            "negative TWAP truncated toward zero"
        );
    }

    function testCrossChainCommitCannotReplay() public {
        bytes memory p = path(address(stable), address(asset));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, 100 ether, 99 ether, deadline);
        vm.chainId(block.chainid + 1);
        vm.expectRevert(DecisionLog.InvalidCommitment.selector);
        vm.prank(agent);
        vault.executeSwap(p, 100 ether, 99 ether, deadline);
    }

    function testOwnerCannotGrantHotKeyOwnershipOrRenounce() public {
        vm.expectRevert(AegisVault.Unauthorized.selector);
        vm.prank(owner);
        vault.transferOwnership(agent);
        vm.expectRevert(AegisVault.Unauthorized.selector);
        vm.prank(owner);
        vault.renounceOwnership();
    }

    function testFuzzTwapPriceStaysWithinBand(uint256 raw) public {
        int24 tick = int24(int256(raw % 2001) - 1000);
        setRelativeTick(tick);
        uint256 p = oracle.price(address(asset));
        require(p > 0 && p > 0.8 ether && p < 1.2 ether, "oracle range");
    }

    function testPermissionlessCheckpointCanOnlyReduceRisk() public {
        buy();
        setRelativeTick(1000);
        vm.prank(outsider);
        vault.checkpoint();
        require(!vault.paused(), "safe checkpoint paused");
        setRelativeTick(-1200);
        uint256 stableBalance = stable.balanceOf(address(vault));
        uint256 assetBalance = asset.balanceOf(address(vault));
        vm.prank(outsider);
        vault.checkpoint();
        require(vault.paused(), "stop not observed");
        eq(stable.balanceOf(address(vault)), stableBalance);
        eq(asset.balanceOf(address(vault)), assetBalance);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, outsider)
        );
        vm.prank(outsider);
        vault.setPaused(false);
    }

    function testDrawdownAcrossDailyBoundaryIsNotReset() public {
        buy();
        uint256 amount = asset.balanceOf(address(vault));
        bytes memory p = path(address(asset), address(stable));
        uint256 deadline = block.timestamp + 30;
        commitSwap(p, amount, amount * 99 / 100, deadline);
        vm.prank(agent);
        vault.executeSwap(p, amount, amount * 99 / 100, deadline);
        vm.warp((block.timestamp / 1 days + 1) * 1 days + 1);
        stable.burn(address(vault), 101 ether);
        vm.prank(outsider);
        vault.checkpoint();
        require(vault.paused(), "drawdown baseline reset at midnight");
    }
}
