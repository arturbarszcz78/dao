"""Byte-exact checks of the xe package against blocks captured from the live testnet.
If any of these fail, nothing the harness signs would be accepted by a node."""

import hashlib

import pytest

from xe.chat import compute_envelope_id, new_envelope, verify_envelope
from xe.directory import new_registration, verify_registration
from xe.encoding import Block, hash_block, sign_block, verify_open_block_signature
from xe.keys import KeyPair, derive_address, verify_hex_signature
from xe.pow import TEST_DIFFICULTY, compute_pow, validate_pow
from xe.statechain import StateBlock, StateOp, build_block, compact_json, hash_state_block, verify_state_signature

from .conftest import NETWORK_ID


@pytest.mark.parametrize("name", ["send", "receive", "burn", "lease", "mint"])
def test_block_hash_matches_testnet(blocks, name):
    d = blocks[name]
    b = Block.from_json(d)
    assert hash_block(b, NETWORK_ID) == d["hash"], name


def test_open_block_pubkey_derives_account_and_signature_verifies(blocks):
    d = blocks["open"]
    assert derive_address(d["pub_key"]) == d["account"]
    verify_open_block_signature(Block.from_json(d), NETWORK_ID)


def test_pow_on_real_blocks(blocks):
    from xe.pow import DEFAULT_DIFFICULTY
    for name in ("send", "receive", "burn"):
        d = blocks[name]
        assert validate_pow(bytes.fromhex(d["hash"]), d["pow_nonce"], DEFAULT_DIFFICULTY), name


def test_sign_block_roundtrip():
    kp = KeyPair.generate()
    b = Block(type="send", account=kp.address, previous="0" * 64, balance=5, timestamp=1, asset="XE",
              destination="ab" * 32, amount=5)
    sign_block(b, kp, NETWORK_ID)
    verify_hex_signature(kp.pub_key_hex, b.signature, bytes.fromhex(b.hash))
    b.pow_nonce = compute_pow(bytes.fromhex(b.hash), TEST_DIFFICULTY)
    assert validate_pow(bytes.fromhex(b.hash), b.pow_nonce, TEST_DIFFICULTY)


def test_statechain_genesis_and_oracle_hash(statechain):
    for key in ("genesis", "oracle"):
        d = statechain[key]
        blk = StateBlock.from_json(d)
        assert hash_state_block(blk) == d["hash"], key
        for sig in d["signatures"]:
            verify_state_signature(d["hash"], sig)


def test_statechain_dao_blocks_if_any(statechain):
    for d in statechain.get("dao", []):
        assert hash_state_block(StateBlock.from_json(d)) == d["hash"]


def test_compact_json_matches_go_rawmessage():
    assert compact_json({"a": "<b>&", "n": 1}) == '{"a":"\\u003cb\\u003e\\u0026","n":1}'


def test_build_block_on_tip(statechain):
    tip = statechain["oracle"]
    op = StateOp.set("dao.registry", {"entity": "XE Network DAO LLC", "version": 1})
    blk = build_block(tip, [op], tip["timestamp"] - 5)  # earlier than tip: must clamp
    assert blk.index == tip["index"] + 1
    assert blk.prev_hash == tip["hash"]
    assert blk.timestamp >= tip["timestamp"]
    assert blk.hash == hash_state_block(blk)
    wire = blk.to_wire()
    assert '"value":{"entity":"XE Network DAO LLC","version":1}' in wire


def test_chat_envelope_roundtrip():
    kp = KeyPair.generate()
    env = new_envelope(kp, "cd" * 32, "hello", difficulty=TEST_DIFFICULTY)
    assert env.id == compute_envelope_id(env.from_, env.pub_key, env.to, env.message, env.timestamp)
    verify_envelope(env, difficulty=TEST_DIFFICULTY)


def test_directory_registration_roundtrip():
    kp = KeyPair.generate()
    reg = new_registration(kp, NETWORK_ID, "12D3KooWtest")
    verify_registration(reg, NETWORK_ID)
    with pytest.raises(Exception):
        verify_registration(reg, "othernet")


def test_address_domain():
    pub = bytes(32)
    assert derive_address(pub.hex()) == hashlib.sha256(b"xe/account/v1" + pub).hexdigest()
