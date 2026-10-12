"""Chain operations the harness performs with company-held keys, plus read-side helpers.

Writes here are limited to what Schedule B allows the harness to do on its own: receive into the
fee account, refund or burn a proposal fee, register in the directory, speak in chat. Nothing
here can touch the treasury or the keyset.
"""

from __future__ import annotations

import asyncio
import time

from xe.client import XeClient, XeError
from xe.encoding import Block, sign_block
from xe.keys import KeyPair
from xe.pow import compute_pow

from .context import Context


async def _pow(hash_hex: str, difficulty: int) -> int:
    # PoW is CPU work; keep it off the event loop.
    return await asyncio.to_thread(compute_pow, bytes.fromhex(hash_hex), difficulty)


async def _tip(chain: XeClient, account: str) -> tuple[str, dict[str, int]]:
    """(previous_hash, balances) for an account; previous == "0" for a fresh account."""
    try:
        page = await chain.chain(account, offset=0, limit=1)
        total = int(page.get("total", 0))
        prev = "0"
        if total > 0:
            last = await chain.chain(account, offset=max(total - 1, 0), limit=1)
            blocks = last.get("blocks", [])
            if blocks:
                prev = blocks[-1]["hash"]
    except XeError as e:
        if e.status != 404:
            raise
        prev = "0"
    bals = await chain.balances(account)
    return prev, bals


async def submit_signed(ctx: Context, b: Block, kp: KeyPair) -> Block:
    sign_block(b, kp, ctx.node.network_id)
    b.pow_nonce = await _pow(b.hash, ctx.node.pow_difficulty)
    await ctx.chain.submit_block(b)
    return b


async def receive_pending(ctx: Context, key_name: str, scope: str = "block.receive") -> list[Block]:
    """Receive every pending send to the account held under `key_name`. Returns the blocks made."""
    kp = ctx.signer.keypair(key_name, scope)
    made: list[Block] = []
    for p in await ctx.chain.pending_for(kp.address):
        prev, bals = await _tip(ctx.chain, kp.address)
        b = Block(type="receive", account=kp.address, previous=prev,
                  balance=bals.get(p["asset"], 0) + p["amount"], timestamp=time.time_ns(),
                  asset=p["asset"], source=p["send_hash"])
        made.append(await submit_signed(ctx, b, kp))
    return made


async def send(ctx: Context, key_name: str, scope: str, destination: str, amount: int, memo: str = "",
               asset: str = "XE") -> Block:
    kp = ctx.signer.keypair(key_name, scope)
    prev, bals = await _tip(ctx.chain, kp.address)
    have = bals.get(asset, 0)
    if have < amount:
        raise XeError(409, f"insufficient {asset} in {key_name}: have {have}, need {amount}")
    b = Block(type="send", account=kp.address, previous=prev, balance=have - amount, timestamp=time.time_ns(),
              asset=asset, destination=destination, amount=amount, memo=memo[:64])
    return await submit_signed(ctx, b, kp)


async def burn(ctx: Context, key_name: str, scope: str, amount: int, memo: str = "", asset: str = "XE") -> Block:
    kp = ctx.signer.keypair(key_name, scope)
    prev, bals = await _tip(ctx.chain, kp.address)
    have = bals.get(asset, 0)
    if have < amount:
        raise XeError(409, f"insufficient {asset} in {key_name}: have {have}, need {amount}")
    b = Block(type="burn", account=kp.address, previous=prev, balance=have - amount, timestamp=time.time_ns(),
              asset=asset, amount=amount, memo=memo[:64])
    return await submit_signed(ctx, b, kp)


# ---- read side ---------------------------------------------------------------------------------

async def account_snapshot(chain: XeClient, account: str, at_ns: int, asset: str = "XE") -> dict:
    """Balance of `asset` as of `at_ns`, plus whether the account existed by then.

    XE accounts are chains; each block carries the post-state balance for its asset, so the balance
    at a time is the balance on the last block of that asset with timestamp <= at_ns.
    """
    try:
        blocks = await chain.full_chain(account)
    except XeError as e:
        if e.status == 404:
            return {"exists": False, "balance": 0, "first_block_ts": None, "snapshot_block": ""}
        raise
    if not blocks:
        return {"exists": False, "balance": 0, "first_block_ts": None, "snapshot_block": ""}
    first_ts = int(blocks[0].get("timestamp", 0))
    bal = 0
    snap = ""
    for b in blocks:
        if int(b.get("timestamp", 0)) > at_ns:
            break
        if b.get("asset") == asset:
            bal = int(b.get("balance", 0))
            snap = b.get("hash", "")
    return {"exists": first_ts <= at_ns, "balance": bal, "first_block_ts": first_ts, "snapshot_block": snap}


async def account_pub_key(chain: XeClient, account: str) -> str:
    """The key declared on the account's open block, or '' if unknown."""
    try:
        page = await chain.chain(account, offset=0, limit=1)
    except XeError as e:
        if e.status == 404:
            return ""
        raise
    blocks = page.get("blocks", [])
    return (blocks[0].get("pub_key") or "") if blocks else ""
