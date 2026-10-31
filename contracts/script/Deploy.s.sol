// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity ^0.8.24;

import {AegisVault} from "../src/AegisVault.sol";
import {DecisionLog} from "../src/DecisionLog.sol";
import {BandedTwapOracle} from "../src/BandedTwapOracle.sol";

interface DeployVm {
    function envString(string calldata) external view returns (string memory);
    function envOr(string calldata, bool) external view returns (bool);
    function readFile(string calldata) external view returns (string memory);
    function parseJsonAddress(string calldata, string calldata) external pure returns (address);
    function parseJsonUint(string calldata, string calldata) external pure returns (uint256);
    function toString(uint256) external pure returns (string memory);
    function startBroadcast() external;
    function stopBroadcast() external;
}

/// @notice Uses a separate deployer keystore. Never reads an owner private key.
/// This script never writes deployments/chain.json; the receipt verifier does that after real confirmation.
contract Deploy {
    DeployVm internal constant vm =
        DeployVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function u16(string memory json, string memory key) internal pure returns (uint16) {
        uint256 value = vm.parseJsonUint(json, key);
        require(value <= type(uint16).max, "uint16 overflow");
        return uint16(value);
    }

    function u32(string memory json, string memory key) internal pure returns (uint32) {
        uint256 value = vm.parseJsonUint(json, key);
        require(value <= type(uint32).max, "uint32 overflow");
        return uint32(value);
    }

    function run() external returns (AegisVault vault, DecisionLog log, BandedTwapOracle oracle) {
        string memory json = vm.readFile(vm.envString("AEGIS_DEPLOY_PLAN"));
        require(vm.parseJsonUint(json, ".schema_version") == 1, "plan schema");
        require(block.chainid == vm.parseJsonUint(json, ".chain_id"), "plan chain mismatch");
        require(block.chainid == 133 || block.chainid == 177, "unsupported deployment chain");
        require(
            block.chainid != 177 || vm.envOr("AEGIS_I_UNDERSTAND_LIVE", false),
            "explicit mainnet confirmation required"
        );
        uint256 observed = vm.parseJsonUint(json, ".observed_block_timestamp");
        require(
            block.timestamp >= observed && block.timestamp - observed <= 300,
            "refresh stale deployment plan"
        );
        address owner = vm.parseJsonAddress(json, ".owner");
        address agent = vm.parseJsonAddress(json, ".agent");
        require(
            owner != address(0) && agent != address(0) && owner != agent,
            "separate owner and agent required"
        );
        uint256 count = vm.parseJsonUint(json, ".market_count");
        require(count > 0 && count < 8, "market count");
        BandedTwapOracle.MarketConfig[] memory markets = new BandedTwapOracle.MarketConfig[](count);
        for (uint256 i; i < count; ++i) {
            string memory prefix = string.concat(".markets[", vm.toString(i), "]");
            uint256 anchor = vm.parseJsonUint(json, string.concat(prefix, ".anchorPriceX18"));
            uint256 fee = vm.parseJsonUint(json, string.concat(prefix, ".fee"));
            require(anchor <= type(uint128).max && fee < 1_000_000, "market integer range");
            markets[i] = BandedTwapOracle.MarketConfig(
                vm.parseJsonAddress(json, string.concat(prefix, ".token")),
                vm.parseJsonAddress(json, string.concat(prefix, ".pool")),
                uint24(fee),
                uint128(anchor),
                u16(json, string.concat(prefix, ".maxDeviationBps")),
                u32(json, string.concat(prefix, ".windowSeconds"))
            );
        }
        uint256 positions = vm.parseJsonUint(json, ".limits.maxPositions");
        require(positions <= 7, "position limit");
        AegisVault.Limits memory caps = AegisVault.Limits(
            u16(json, ".limits.maxTradeBps"),
            u16(json, ".limits.maxSlippageBps"),
            u16(json, ".limits.maxTradesPerDay"),
            u16(json, ".limits.dailyLossLimitBps"),
            u16(json, ".limits.maxDrawdownBps"),
            u16(json, ".limits.maxTokenExposureBps"),
            u16(json, ".limits.maxTradesPerHour"),
            u16(json, ".limits.stopLossBps"),
            u16(json, ".limits.takeProfitBps"),
            u16(json, ".limits.trailingStopBps"),
            u32(json, ".limits.cooldownSeconds"),
            u32(json, ".limits.maxHoldingSeconds"),
            uint8(positions)
        );
        vm.startBroadcast();
        oracle = new BandedTwapOracle(
            owner,
            vm.parseJsonAddress(json, ".settlement"),
            vm.parseJsonAddress(json, ".factory"),
            markets
        );
        log = new DecisionLog(owner, agent);
        vault = new AegisVault(
            owner,
            agent,
            vm.parseJsonAddress(json, ".router"),
            address(log),
            address(oracle),
            vm.parseJsonAddress(json, ".wrapped_native"),
            caps
        );
        log.bindVault(address(vault));
        vm.stopBroadcast();
        // Require a usable observation before an operator proceeds to funding.
        require(
            oracle.price(vm.parseJsonAddress(json, ".wrapped_native")) > 0, "oracle unavailable"
        );
        require(vault.paused() && log.vault() == address(vault), "deployment binding failed");
    }
}
