// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

contract DecisionLog is Ownable {
    struct Commitment {
        bytes32 decisionHash;
        bytes32 executionHash;
        address committer;
        uint64 committedBlock;
        uint64 committedAt;
        bool consumed;
        bool revealed;
    }
    address public agent;
    address public vault;
    address public immutable initializer;
    uint256 public count;
    mapping(uint256 => Commitment) public commitments;
    mapping(address => uint256) public pending;
    mapping(uint256 => bool) public keeperCommitments;

    error Unauthorized();
    error InvalidCommitment();
    error PendingDecision();
    error InvalidReveal();
    event Committed(
        uint256 indexed id,
        address indexed committer,
        bytes32 decisionHash,
        bytes32 executionHash,
        uint256 timestamp
    );
    event Consumed(uint256 indexed id, bytes32 executionHash, uint256 timestamp);
    event Revealed(uint256 indexed id, bytes payload, uint256 timestamp);
    event VaultBound(address indexed vault);
    event AgentChanged(address indexed agent);

    constructor(address initialOwner, address initialAgent) Ownable(initialOwner) {
        if (initialAgent == address(0) || initialAgent == initialOwner) revert Unauthorized();
        agent = initialAgent;
        initializer = msg.sender;
    }

    function bindVault(address target) external {
        if (
            (msg.sender != owner() && msg.sender != initializer) || vault != address(0)
                || target.code.length == 0
        ) revert Unauthorized();
        vault = target;
        emit VaultBound(target);
    }

    function setAgent(address next) external onlyOwner {
        if (next == address(0) || next == owner()) revert Unauthorized();
        agent = next;
        emit AgentChanged(next);
    }

    function commit(bytes32 decisionHash) external returns (uint256) {
        return _commit(decisionHash, bytes32(0));
    }

    function commit(bytes32 decisionHash, bytes32 executionHash) external returns (uint256) {
        return _commit(decisionHash, executionHash);
    }

    function _commit(bytes32 decisionHash, bytes32 executionHash) internal returns (uint256 id) {
        if (msg.sender != agent) revert Unauthorized();
        return _storeCommitment(decisionHash, executionHash);
    }

    /// @notice Permissionless safety-exit intents. These cannot authorize agent entries.
    function commitKeeper(bytes32 decisionHash, bytes32 executionHash)
        external
        returns (uint256 id)
    {
        if (executionHash == bytes32(0)) revert InvalidCommitment();
        id = _storeCommitment(decisionHash, executionHash);
        keeperCommitments[id] = true;
    }

    function _storeCommitment(bytes32 decisionHash, bytes32 executionHash)
        internal
        returns (uint256 id)
    {
        if (decisionHash == bytes32(0)) revert InvalidCommitment();
        if (pending[msg.sender] != 0) revert PendingDecision();
        id = ++count;
        commitments[id] = Commitment(
            decisionHash,
            executionHash,
            msg.sender,
            uint64(block.number),
            uint64(block.timestamp),
            false,
            false
        );
        pending[msg.sender] = id;
        emit Committed(id, msg.sender, decisionHash, executionHash, block.timestamp);
    }

    function consume(address committer, bytes32 executionHash) external returns (uint256 id) {
        return _consume(committer, executionHash, false);
    }

    function consumeKeeper(address committer, bytes32 executionHash) external returns (uint256 id) {
        return _consume(committer, executionHash, true);
    }

    function _consume(address committer, bytes32 executionHash, bool keeper)
        internal
        returns (uint256 id)
    {
        if (msg.sender != vault) revert Unauthorized();
        id = pending[committer];
        Commitment storage c = commitments[id];
        if (
            id == 0 || c.committer != committer || c.consumed || c.revealed
                || executionHash == bytes32(0) || c.executionHash != executionHash
                || block.number <= c.committedBlock || keeperCommitments[id] != keeper
        ) revert InvalidCommitment();
        c.consumed = true;
        pending[committer] = 0;
        emit Consumed(id, executionHash, block.timestamp);
    }

    function reveal(uint256 id, bytes calldata payload) external {
        Commitment storage c = commitments[id];
        if (c.committer != msg.sender || c.revealed || keccak256(payload) != c.decisionHash) {
            revert InvalidReveal();
        }
        c.revealed = true;
        if (pending[msg.sender] == id) pending[msg.sender] = 0;
        emit Revealed(id, payload, block.timestamp);
    }
}
