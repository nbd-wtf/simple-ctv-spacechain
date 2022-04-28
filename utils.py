import io
import json
import struct
import shelve
import hashlib
from typing import List, Optional
from dataclasses import dataclass
from contextlib import contextmanager
from test_framework import script
from test_framework.messages import (
    COIN,
    COutPoint,
    CTxWitness,
    CTransaction,
    CTxInWitness,
    CScriptWitness,
)
from test_framework.script import CScript, OPCODE_NAMES
from buidl.hd import HDPrivateKey, PrivateKey
from rpc import BitcoinRPC, JSONRPCError

rpc = BitcoinRPC(net_name="signet")


def log(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


@contextmanager
def s():
    try:
        db = shelve.open("spacechain.db", writeback=True)
        yield db
    finally:
        db.close()


@dataclass
class SpacechainTx:
    tmpl_bytes: Optional[bytes]
    id: Optional[str] = None
    spacechain_block_hash: Optional[bytes] = None

    @property
    def template(self):
        if self.tmpl_bytes:
            tx = CTransaction()
            tx.deserialize(io.BytesIO(self.tmpl_bytes))
            tx.rehash()
            return tx

    def ctv_hash(self, input_index=0):
        return self.template.get_standard_template_hash(input_index)


@dataclass
class Wallet:
    privkey: PrivateKey
    coins: List["Coin"]

    @classmethod
    def generate(cls, seed: bytes) -> "Wallet":
        return cls(
            HDPrivateKey.from_seed(seed, network="signet").get_private_key(1),
            [],
        )

    def scan(self):
        res = rpc.scantxoutset("start", [f"addr({self.address})"])
        for utxo in res["unspents"]:
            self.coins.append(
                Coin(
                    COutPoint(int(utxo["txid"], 16), utxo["vout"]),
                    int(utxo["amount"] * COIN),
                    utxo["height"],
                )
            )

    @property
    def address(self):
        return self.privkey.point.p2wpkh_address(network="signet")

    @property
    def max_sendable(self):
        if not self.coins:
            return 0
        return max([coin.satoshis for coin in self.coins])

    @property
    def biggest_coin(self):
        for coin in self.coins:
            if coin.satoshis == self.max_sendable:
                return coin

        raise ValueError("no coins!")

    def sign(self, tx: CTransaction, input_index: int, satoshis: int):
        pubkey160 = self.privkey.point.hash160()

        sighash = script.SegwitV0SignatureHash(
            # this is how the p2wpkh redeem script looks for sighashes
            CScript(
                [
                    script.OP_DUP,
                    script.OP_HASH160,
                    pubkey160,
                    script.OP_EQUALVERIFY,
                    script.OP_CHECKSIG,
                ]
            ),
            tx,
            input_index,
            script.SIGHASH_ALL,
            amount=satoshis,
        )

        sig = self.privkey.sign(int.from_bytes(sighash, "big")).der() + bytes(
            [script.SIGHASH_ALL]
        )
        tx.wit.vtxinwit.append(CTxInWitness())
        tx.wit.vtxinwit.append(CTxInWitness())
        tx.wit.vtxinwit[1].scriptWitness.stack = [
            sig,
            self.privkey.point.sec(),
        ]

        return CTransaction(tx)


@dataclass(frozen=True)
class Coin:
    outpoint: COutPoint
    satoshis: int
    height: int


def format_cscript(script: CScript) -> str:
    return " ".join(
        [str(el) if el in OPCODE_NAMES else shorten(el.hex()) for el in script]
    )


def shorten(s: str) -> str:
    return s[0:4] + "…" + s[-3:]


def make_color(start, end):
    def color_func(s):
        return start + t_(str(s)) + end

    return color_func


def esc(*codes) -> str:
    """
    Produces an ANSI escape code from a list of integers
    """
    return t_("\x1b[{}m").format(t_(";").join(t_(str(c)) for c in codes))


def t_(b) -> str:
    """ensure text type"""
    if isinstance(b, bytes):
        return b.decode()
    return b


FG_END = esc(39)
red = make_color(esc(31), FG_END)
green = make_color(esc(32), FG_END)
yellow = make_color(esc(33), FG_END)
blue = make_color(esc(34), FG_END)
magenta = make_color(esc(35), FG_END)
cyan = make_color(esc(36), FG_END)
white = make_color(esc(37), FG_END)
bold = make_color(esc(1), esc(22))
italic = make_color(esc(3), esc(23))
underline = make_color(esc(4), esc(24))
