// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title FaceVerifyChain
 * @notice Stores SHA-256 hashes of face-match records on-chain.
 *         Each hash maps to the block timestamp and the submitter address.
 *
 * Layout
 * ------
 *  hash (bytes32)  →  AnchorRecord { timestamp, submitter }
 *
 * Only the first anchor for a given hash is recorded (subsequent anchors of
 * the same hash are no-ops so callers can safely call anchor() idempotently).
 */
contract FaceVerifyChain {

    struct AnchorRecord {
        uint256 anchoredAt;   // block.timestamp when first anchored
        address submitter;    // msg.sender of the anchoring tx
    }

    /// @notice hash → anchor record
    mapping(bytes32 => AnchorRecord) public records;

    /// @notice emitted whenever a new (previously unseen) hash is anchored
    event Anchored(bytes32 indexed recordHash, uint256 anchoredAt, address indexed submitter);

    /**
     * @notice Anchor a record hash on-chain.
     * @param recordHash SHA-256 hash of the match record (bytes32).
     *                   If already present, the call is silently ignored.
     */
    function anchor(bytes32 recordHash) external {
        if (records[recordHash].anchoredAt != 0) {
            // Already anchored — idempotent, no revert
            return;
        }
        records[recordHash] = AnchorRecord({
            anchoredAt: block.timestamp,
            submitter:  msg.sender
        });
        emit Anchored(recordHash, block.timestamp, msg.sender);
    }

    /**
     * @notice Check whether a hash has been anchored.
     * @return anchoredAt  Block timestamp of anchoring (0 if not found).
     * @return submitter   Address that anchored (zero address if not found).
     */
    function verify(bytes32 recordHash)
        external
        view
        returns (uint256 anchoredAt, address submitter)
    {
        AnchorRecord memory r = records[recordHash];
        return (r.anchoredAt, r.submitter);
    }
}
