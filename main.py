import sys
import pprint
import argparse
from dataclasses import dataclass

from bitcoin.core import (
    CTransaction,
    CMutableTransaction,
    CTxIn,
    CTxOut,
    CScript,
    CScriptOp,
    COutPoint,
    CTxWitness,
    CTxInWitness,
    CScriptWitness,
    COIN,
)
from bitcoin.core import script
from bitcoin.wallet import CBech32BitcoinAddress
from buidl.hd import HDPrivateKey, PrivateKey
from buidl.ecc import S256Point
from rpc import BitcoinRPC, JSONRPCError
from utils import *

CHAIN_MAX = 3
SATS_AMOUNT = 1000
OP_CHECKTEMPLATEVERIFY = script.OP_NOP4
anyone_can_spend = CScript([script.OP_TRUE])

colors = {
    0: {
        "prevout": lambda x: magenta(x),
        "txid": lambda x: cyan(x),
    },
    1: {
        "prevout": lambda x: cyan(x),
        "txid": lambda x: green(x),
    },
    2: {
        "prevout": lambda x: green(x),
        "txid": lambda x: blue(x),
    },
    3: {
        "prevout": lambda x: blue(x),
        "txid": lambda x: magenta(x),
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("seed")
    argv = parser.parse_args(sys.argv)

    print(f'> generating transactions for spacechain "{argv.seed}"...')
    txs = pregenerate_transactions(argv.seed)

    for i in range(len(txs)):
        txid_color = lambda x: colors[i % len(colors)]["txid"](bold(x))
        prevout_color = lambda x: colors[i % len(colors)]["prevout"](bold(x))
        ctv_color = lambda x: red(x)

        tx = txs[i]
        shorten_txid = shorten(bytes_to_txid(tx.GetTxid()))
        if i < len(txs) - 1:
            shorten_txid = txid_color(shorten_txid)

        print(bold(f"tx {i+1} ~"))
        print(f"  id: {bold(shorten_txid)}")

        if i > 0:
            shorten_ctv_hash = ctv_color(
                shorten(get_standard_template_hash(tx, 0).hex())
            )
            print(f"  CTV hash: {shorten_ctv_hash}")

        # inputs
        if i == 0:
            print(f"    vin[0] = empty")
        else:
            prevout_0_txid, prevout_0_n = str(tx.vin[0].prevout).split(":")
            shorten_prevout_0 = ":".join(
                [prevout_color(shorten(prevout_0_txid)), prevout_0_n]
            )
            redeem_script_0 = " ".join(
                [
                    "OP_CHECKTEMPLATEVERIFY"
                    if el == CScriptOp(0xB3)
                    else shorten(el.hex())
                    for el in tx.vin[0].scriptSig
                ]
            )
            if "OP_CHECKTEMPLATEVERIFY" in redeem_script_0:
                redeem_script_0 = "{" + ctv_color(redeem_script_0) + "}"

            sh = prevout_color(shorten(sha256(tx.vin[0].scriptSig).hex()))
            print(f"    vin[0] = [{shorten_prevout_0}] {redeem_script_0} (hash: {sh})")
        if len(tx.vin) > 1:
            print(f"    vin[1] = empty")

        # outputs
        outscript_0 = format_cscript(tx.vout[0].scriptPubKey)
        if "OP_RETURN" not in outscript_0:
            outscript_0 = "{" + txid_color(outscript_0) + "}"

        print(f"    vout[0] = {italic(tx.vout[0].nValue)}sat 🠖 {outscript_0}")
        if len(tx.vout) > 1:
            outscript_1 = white("{" + format_cscript(tx.vout[1].scriptPubKey) + "}")
            print(f"    vout[1] = {italic(tx.vout[1].nValue)}sat 🠖 {outscript_1}")


def pregenerate_transactions(seed):
    txs_reversed = []
    last = CMutableTransaction()
    last.nVersion = 2
    last.vin = [CTxIn()]  # blank because CTV in p2wsh
    last.vout = [
        CTxOut(
            0,
            # the chain of transactions ends here with an OP_RETURN
            CScript([script.OP_RETURN, seed.encode("utf-8")]),
        )
    ]
    txs_reversed.append(last)
    next = last

    for i in range(CHAIN_MAX):
        redeem_script = CScript(
            [
                get_standard_template_hash(next, 0),  # ctv hash
                OP_CHECKTEMPLATEVERIFY,
            ]
        )

        prev = CMutableTransaction()
        prev.nVersion = 2
        prev.vin = [CTxIn(), CTxIn()]  # blank because CTV in p2wsh uses blank here
        prev.vout = [
            # this output continues the transaction chain
            CTxOut(
                SATS_AMOUNT,
                # standard p2wsh output:
                CScript([script.OP_0, sha256(redeem_script)]),
            ),
            # this output is used for CPFP and for the miner to include the hash
            CTxOut(
                SATS_AMOUNT * 3,
                # standard p2wsh output:
                CScript([script.OP_0, sha256(anyone_can_spend)]),
            ),
        ]

        txs_reversed.append(prev)
        next = prev

    # reverse the list so we start with the first transaction
    txs_normal = list(reversed(txs_reversed))

    # and also add the correct inputs
    txs = []
    for i in range(0, len(txs_normal)):
        this = txs_normal[i]
        prev = txs_normal[i - 1]
        this.vin[0] = CTxIn(
            COutPoint(prev.GetTxid(), 0),
            # redeem_script
            CScript(
                [
                    get_standard_template_hash(this, 0),  # ctv hash
                    OP_CHECKTEMPLATEVERIFY,
                ]
            ),
        )
        txs.append(this)

    first = txs_normal[0]
    first.vin = [first.vin[0]]

    return [first, *txs]


if __name__ == "__main__":
    main()
