// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV3Factory {
    function getPool(address, address, uint24) external view returns (address);
}

interface IV3Pool {
    function factory() external view returns (address);
    function token0() external view returns (address);
    function token1() external view returns (address);
    function fee() external view returns (uint24);
    function observe(uint32[] calldata) external view returns (int56[] memory, uint160[] memory);
}

interface ISwapRouter02 {
    struct ExactInputParams {
        bytes path;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
    }
    function factory() external view returns (address);
    function WETH9() external view returns (address);
    function exactInput(ExactInputParams calldata) external payable returns (uint256);
}

interface IWrappedNative {
    function deposit() external payable;
}
