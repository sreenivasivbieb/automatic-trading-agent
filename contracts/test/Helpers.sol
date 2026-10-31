// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {ISwapRouter02} from "../src/interfaces/IDex.sol";

interface Vm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }
    function prank(address) external;
    function startPrank(address) external;
    function stopPrank() external;
    function expectRevert() external;
    function expectRevert(bytes4) external;
    function expectRevert(bytes calldata) external;
    function warp(uint256) external;
    function roll(uint256) external;
    function deal(address, uint256) external;
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
    function envOr(string calldata, bool) external returns (bool);
    function skip(bool) external;
    function etch(address, bytes calldata) external;
    function chainId(uint256) external;
}

abstract contract TestBase {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function eq(uint256 a, uint256 b) internal pure {
        require(a == b, "uint mismatch");
    }

    function eq(address a, address b) internal pure {
        require(a == b, "address mismatch");
    }
}

contract MockToken is IERC20Metadata {
    string public name;
    string public symbol;
    uint8 public immutable decimals;
    uint256 public totalSupply;
    uint256 public feeBps;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory label, uint8 d) {
        name = label;
        symbol = label;
        decimals = d;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
        emit Transfer(address(0), to, amount);
    }

    function burn(address from, uint256 amount) external {
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    function setFee(uint256 bps) external {
        feeBps = bps;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        balanceOf[from] -= amount;
        uint256 fee = amount * feeBps / 10000;
        balanceOf[to] += amount - fee;
        totalSupply -= fee;
        emit Transfer(from, to, amount - fee);
    }

    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply += msg.value;
    }
}

contract MockFactory {
    mapping(bytes32 => address) private pools;

    function key(address a, address b, uint24 fee) internal pure returns (bytes32) {
        return keccak256(abi.encode(a < b ? a : b, a < b ? b : a, fee));
    }

    function setPool(address a, address b, uint24 fee, address pool) external {
        pools[key(a, b, fee)] = pool;
    }

    function getPool(address a, address b, uint24 fee) external view returns (address) {
        return pools[key(a, b, fee)];
    }
}

contract MockPool {
    address public immutable factory;
    address public immutable token0;
    address public immutable token1;
    uint24 public immutable fee;
    int24 public tick;
    bool public broken;
    int56 public remainder;

    constructor(address f, address a, address b, uint24 tier) {
        factory = f;
        token0 = a < b ? a : b;
        token1 = a < b ? b : a;
        fee = tier;
    }

    function setTick(int24 value) external {
        tick = value;
    }

    function setBroken(bool value) external {
        broken = value;
    }

    function setRemainder(int56 value) external {
        remainder = value;
    }

    function observe(uint32[] calldata secondsAgos)
        external
        view
        returns (int56[] memory cumulative, uint160[] memory liquidity)
    {
        require(!broken, "no observation history");
        cumulative = new int56[](2);
        liquidity = new uint160[](2);
        cumulative[1] = int56(tick) * int56(uint56(secondsAgos[0])) + remainder;
    }
}

interface IReentryCallback {
    function onSwap(bytes calldata, uint256, uint256) external;
}

contract MockRouter is ISwapRouter02 {
    address public immutable factory;
    address public immutable WETH9;
    address public lastRecipient;
    uint256 public outputBps = 9970;
    bool public badReport;
    address public callback;

    constructor(address f, address wrapped) {
        factory = f;
        WETH9 = wrapped;
    }

    function setOutputBps(uint256 value) external {
        outputBps = value;
    }

    function setBadReport(bool value) external {
        badReport = value;
    }

    function setCallback(address target) external {
        callback = target;
    }

    function exactInput(ExactInputParams calldata p) external payable returns (uint256 result) {
        bytes calldata path = p.path;
        address first;
        address last;
        uint256 end = path.length - 20;
        assembly {
            first := shr(96, calldataload(path.offset))
            last := shr(96, calldataload(add(path.offset, end)))
        }
        IERC20Metadata(first).transferFrom(msg.sender, address(this), p.amountIn);
        result = p.amountIn * outputBps / 10000;
        lastRecipient = p.recipient;
        if (callback != address(0)) {
            IReentryCallback(callback).onSwap(path, p.amountIn, p.amountOutMinimum);
        }
        require(result >= p.amountOutMinimum, "router minimum");
        IERC20Metadata(last).transfer(p.recipient, result);
        return badReport ? result + 1 : result;
    }
}
