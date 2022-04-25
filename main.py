import sys
import pprint
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
    with s() as db:
        db["seed"] = db.get("seed") or str(random.random()).encode("utf-8")
        db["txs"] = db.get("txs") or {}

        current_size = db.get("size")
        if current_size != CHAIN_MAX:
            db["size"] = CHAIN_MAX
            db["txs"] = {}

        global wallet
        wallet = Wallet.generate(db["seed"])

    generate_transactions_flow()
    get_money_flow()

    genesis = get_tx(0)
    if not genesis.id:
        # we don't know about the spacechain genesis block, so let's create one
        bootstrap_flow()

    find_spacechain_position_flow()


def find_spacechain_position_flow():
    print()
    print(yellow(f"searching for the spacechain tip..."))
    for i in range(CHAIN_MAX):
        with s() as db:
            txid = db["txs"][i].id
            if not txid:
                print(f"  - transaction {i} not mined yet, mine it?")
                return i

            tx = ctvsignet(f"/tx/{txid}")
            print(tx)

            print(f"  - transaction {i} mined as {bold(white(txid))}")
            r = requests.get(f"https://explorer.ctvsignet.com/api/tx/{txid}/outspends")
            r.raise_for_status()

    return CHAIN_MAX


def bootstrap_flow():
    print()
    print(
        yellow(
            f"> let's bootstrap the spacechain sending its first covenant transaction."
        )
    )
    first = get_tx(0)
    target_script = cyan(
        get_standard_template_hash(first.template, 0).hex() + " OP_CHECKTEMPLATEVERIFY"
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
                    get_standard_template_hash(first.template, 0),  # CTV hash
                    OP_CHECKTEMPLATEVERIFY,
                ]
            ),
        ),
        # change
        CTxOut(
            coin.satoshis - SATS_AMOUNT - 800,
            CScript([0, wallet.privkey.point.hash160()]),
        ),
    ]
    tx = coin.sign(bootstrap, 0)
    print(f"{white(tx.serialize().hex())}")
    input(f"  (press Enter to publish)")
    txid = ctvsignet("/tx", tx.serialize().hex())
    print(yellow(f"> published {bold(white(txid))}."))
    with s() as db:
        db["txs"][0].id = txid


def get_money_flow():
    global wallet
    private_key = bold(white(shorten(wallet.privkey.hex())))
    print(yellow(f"> loaded wallet with private key {private_key}"))

    while True:
        print(yellow(f"> scanning user wallet {magenta(bold(wallet.address))}"))
        wallet.scan()
        print(f"  UTXOs: {len(wallet.coins)}")
        for utxo in wallet.coins:
            print(f"  - {utxo.satoshis} satoshis")

        if wallet.max_sendable > SATS_AMOUNT + 1000:
            break

        print(
            yellow(
                f"> fund your wallet by sending money to {white(bold(wallet.address))}"
            )
        )
        input("  (press Enter when you're done)")


def generate_transactions_flow():
    print(yellow(f"> generating transactions for spacechain..."))
    templates = [get_tx(i).template for i in range(CHAIN_MAX + 1)]
    for i in range(len(templates)):
        tmpl = templates[i]
        ctv_hash = cyan(get_standard_template_hash(tmpl, 0).hex())
        print(f"  - [{i}] ctv hash: {ctv_hash}")


def get_tx(i) -> SpacechainTx:
    with s() as db:
        if i in db["txs"]:
            return db["txs"][i]

    # the last tx in the chain is always the same
    if i == CHAIN_MAX + 1:
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

        with s() as db:
            db["txs"][i] = SpacechainTx(tmpl_bytes=marshal_tx(last), id=None)
    else:
        # recursion: we need the next one to calculate its CTV hash and commit here
        next = get_tx(i + 1).template
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
                # bare CTV
                CScript(
                    [
                        get_standard_template_hash(next, 0),  # CTV hash
                        OP_CHECKTEMPLATEVERIFY,
                    ]
                ),
            ),
        ]

        with s() as db:
            db["txs"][i] = SpacechainTx(tmpl_bytes=marshal_tx(tx), id=None)

    return get_tx(i)


if __name__ == "__main__":
    main()
