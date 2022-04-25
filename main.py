import sys
import pprint
import shelve
import random

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
from utils import *

OP_CHECKTEMPLATEVERIFY = script.OP_NOP4
CHAIN_MAX = 4
SATS_AMOUNT = 1000

wallet = None


def main():
    with shelve.open("spacechain.db") as db:
        db["seed"] = db.get("seed") or str(random.random()).encode("utf-8")
        db["txs"] = db.get("txs") or {}

        current_size = db.get("size")
        if current_size != CHAIN_MAX:
            db["size"] = CHAIN_MAX
            db["txs"] = {}

        wallet = Wallet.generate(db["seed"])

    private_key = bold(white(shorten(wallet.privkey.hex())))
    print(yellow(f"> loaded wallet with private key {private_key}"))

    print(yellow(f"> generating transactions for spacechain..."))
    txs = [get_tx(i) for i in range(CHAIN_MAX + 1)]
    for i in range(len(txs)):
        tx = txs[i]
        ctv_hash = cyan(get_standard_template_hash(tx, 0).hex())
        print(f"- [{i}] ctv hash: {ctv_hash}")

    print(yellow(f"> scanning user wallet"))
    wallet.scan()
    print(f"UTXOs: {len(wallet.coins)}")
    for utxo in wallet.coins:
        print(f"- {utxo.satoshis} satoshis")

    while wallet.max_sendable < SATS_AMOUNT + 1000:
        print(
            yellow(
                f"> fund your wallet by sending money to {white(bold(wallet.address))}"
            )
        )
        input("  (press Enter when you're done)")

    print(
        yellow(
            f"> let's try to bootstrap the spacechain by its first covenant transaction."
        )
    )
    first = get_tx(0)
    target_script = cyan(
        get_standard_template_hash(first, 0).hex() + " OP_CHECKTEMPLATEVERIFY"
    )
    print(
        yellow(f"> we'll do that by creating an output that spends to {target_script}")
    )
    coin = wallet.biggest_coin
    bootstrap = CMutableTransaction()
    bootstrap.nVersion = 2
    bootstrap.vin = [CTxIn(coin.outpoint)]
    bootstrap.vout = [
        # to spacechain
        CTxOut(
            SATS_AMOUNT,
            CScript(
                # bare CTV (make bare scripts great again)
                [
                    get_standard_template_hash(first, 0),  # CTV hash
                    OP_CHECKTEMPLATEVERIFY,
                ]
            ),
        ),
        # change
        CTxOut(
            coin.satoshis - SATS_AMOUNT - 800,
            CScript([0, sha256(coin.scriptPubKey)]),
        ),
    ]
    tx = coin.sign(bootstrap, 0)
    print(f"  {white(tx.serialize().hex())}")
    input()


def get_tx(i):
    with shelve.open("spacechain.db") as db:
        if i in db["txs"]:
            return db["txs"][i]

    # the last tx in the chain is always the same
    if i == CHAIN_MAX:
        last = CMutableTransaction()
        last.nVersion = 2
        last.vin = [CTxIn()]  # CTV works with blank inputs
        last.vout = [
            CTxOut(
                0,
                # the chain of transactions ends here with an OP_RETURN
                CScript([script.OP_RETURN, "simple-spacechain".encode("utf-8")]),
            )
        ]

        with shelve.open("spacechain.db") as db:
            db["txs"][i] = last

        return last

    # recursion: we need the next one to calculate its CTV hash and commit here
    next = get_tx(i + 1)
    redeem_script = CScript(
        [
            get_standard_template_hash(next, 0),  # CTV hash
            OP_CHECKTEMPLATEVERIFY,
        ]
    )
    tx = CMutableTransaction()
    tx.nVersion = 2
    tx.vin = [
        # CTV works with blank inputs, we will fill in later
        # one for the previous tx in the chain, the other for fee-bidding
        CTxIn(),
        CTxIn(),
    ]
    tx.vout = [
        # this output continues the transaction chain
        CTxOut(
            SATS_AMOUNT,
            # standard p2wsh output:
            CScript([script.OP_0, sha256(redeem_script)]),
        ),
    ]

    with shelve.open("spacechain.db") as db:
        db["txs"][i] = tx

    return tx


if __name__ == "__main__":
    main()
