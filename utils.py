import io
import json
import struct
import shelve
import hashlib
from typing import List, Optional
from dataclasses import dataclass
from contextlib import contextmanager
from bitcoin.core import (
    script,
    CMutableTransaction,
    CTransaction,
    COutPoint,
    COIN,
    CTxWitness,
    CTxInWitness,
    CScriptWitness,
)
from bitcoin.core.script import CScript, OPCODE_NAMES
from bitcoin.wallet import CBech32BitcoinAddress
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
    id: Optional[str]
    spacechain_block_hash: Optional[bytes]

    @property
    def template(self):
        if self.tmpl_bytes:
            return unmarshal_tx(self.tmpl_bytes)


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
                    self,
                    COutPoint(txid_to_bytes(utxo["txid"]), utxo["vout"]),
                    int(utxo["amount"] * COIN),
                    bytes.fromhex(utxo["scriptPubKey"]),
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


@dataclass(frozen=True)
class Coin:
    wallet: Wallet
    outpoint: COutPoint
    satoshis: int
    scriptPubKey: bytes
    height: int

    def sign(self, tx: CMutableTransaction, input_index: int):
        spend_from_addr = CBech32BitcoinAddress.from_scriptPubKey(
            CScript(self.scriptPubKey)
        )

        # standard p2wpkh redeemScript
        redeem_script = CScript(
            [
                script.OP_DUP,
                script.OP_HASH160,
                spend_from_addr,
                script.OP_EQUALVERIFY,
                script.OP_CHECKSIG,
            ]
        )

        sighash = script.SignatureHash(
            redeem_script,
            tx,
            input_index,
            script.SIGHASH_ALL,
            amount=self.satoshis,
            sigversion=script.SIGVERSION_WITNESS_V0,
        )
        sig = self.wallet.privkey.sign(int.from_bytes(sighash, "big")).der() + bytes(
            [script.SIGHASH_ALL]
        )
        wit = [CTxInWitness(CScriptWitness([sig, self.wallet.privkey.point.sec()]))]
        tx.wit = CTxWitness(wit)
        return CTransaction.from_tx(tx)


def sha256(s) -> bytes:
    return hashlib.sha256(s).digest()


def ser_compact_size(l) -> bytes:
    r = b""
    if l < 253:
        r = struct.pack("B", l)
    elif l < 0x10000:
        r = struct.pack("<BH", 253, l)
    elif l < 0x100000000:
        r = struct.pack("<BI", 254, l)
    else:
        r = struct.pack("<BQ", 255, l)
    return r


def ser_string(s) -> bytes:
    return ser_compact_size(len(s)) + s


def get_standard_template_hash(tx: CTransaction, nIn: int) -> bytes:
    r = b""
    r += struct.pack("<i", tx.nVersion)
    r += struct.pack("<I", tx.nLockTime)
    vin = tx.vin or []
    vout = tx.vout or []
    for i in range(len(vin)):
        inp = vin[i]
        if inp.scriptSig and inp.scriptSig.is_p2sh():
            print(i, inp.scriptSig.is_p2sh())
            r += sha256(ser_string(inp.scriptSig))
    r += struct.pack("<I", len(tx.vin))
    r += sha256(b"".join(struct.pack("<I", inp.nSequence) for inp in vin))
    r += struct.pack("<I", len(tx.vout))
    r += sha256(b"".join(out.serialize() for out in vout))
    r += struct.pack("<I", nIn)
    return sha256(r)


def format_cscript(script: CScript) -> str:
    return " ".join(
        [str(el) if el in OPCODE_NAMES else shorten(el.hex()) for el in script]
    )


def txid_to_bytes(txid: str) -> bytes:
    """Convert the txids output by Bitcoin Core (little endian) to bytes."""
    return bytes.fromhex(txid)[::-1]


def bytes_to_txid(b: bytes) -> str:
    """Convert big-endian bytes to Core-style txid str."""
    return b[::-1].hex()


def shorten(s: str) -> str:
    return s[0:4] + "…" + s[-3:]


def to_outpoint(txid: str, n: int) -> COutPoint:
    return COutPoint(txid_to_bytes(txid), n)


def marshal_tx(tx: CTransaction) -> bytes:
    f = io.BytesIO()
    tx.stream_serialize(f, True)
    raw = f.getvalue()
    return raw


def unmarshal_tx(b: bytes) -> CMutableTransaction:
    f = io.BytesIO(b)
    tx = CTransaction.stream_deserialize(f)
    return CMutableTransaction.from_tx(tx)


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
