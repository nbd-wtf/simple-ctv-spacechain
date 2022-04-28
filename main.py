import sys
import time
import pprint
import random

from test_framework import script
from test_framework.messages import (
    COIN,
    CTxIn,
    CTxOut,
    COutPoint,
    CTxWitness,
    CTransaction,
    CTxInWitness,
)
from test_framework.script import CScript
from utils import *

CHAIN_MAX = 7
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

    pos = find_spacechain_position_flow()

    if pos == -1:
        print(yellow(f"> this spacechain has reached its end."))
        return

    while True:
        pos = mine_next_block_flow(pos)

        find_spacechain_position_flow()

        if pos > CHAIN_MAX:
            break

        get_money_flow()


def mine_next_block_flow(next_pos):
    print()
    print(yellow(f"> we're going to mine the spacechain block {next_pos}"))

    fee_bid = 0
    spacechain_block_hash = b""

    while fee_bid == 0:
        try:
            fee_bid = int(
                input(
                    blue(
                        bold(
                            f"  ~ type the fee you want to bid (in satoshis, type 3000 if you're unsure): "
                        )
                    )
                )
            )
        except ValueError:
            pass

    while spacechain_block_hash == b"":
        try:
            spacechain_block_hash = input(
                blue(bold(f"  ~ type the block hash (anything, this is just a test): "))
            ).encode("utf-8")
        except ValueError:
            pass

    # our transaction
    min_relay_fee = 300
    coin = wallet.biggest_coin
    our = CTransaction()
    our.nVersion = 2
    our.vin = [CTxIn(coin.outpoint, nSequence=0)]
    our.vout = [
        # to spacechain
        CTxOut(
            fee_bid,
            CScript(
                # normal p2wpkh to our same address always
                CScript([0, wallet.privkey.point.hash160()]),
            ),
        ),
        # op_return
        CTxOut(0, CScript([script.OP_RETURN, spacechain_block_hash])),
        # change
        CTxOut(
            coin.satoshis - fee_bid - min_relay_fee,
            CScript([0, wallet.privkey.point.hash160()]),
        ),
    ]
    our_tx = wallet.sign(our, 0, coin.satoshis)
    our_tx.rehash()

    # spacechain transaction
    spc = CTransaction(get_tx(next_pos).template)
    spc.vin = []
    if next_pos > 0:
        # from the previous spacechain transaction
        spc.vin.append(
            CTxIn(
                COutPoint(int(get_tx(next_pos - 1).id, 16), 0),
                nSequence=0,
            ),
        )
        spc_tx = spc

    spc.vin.append(
        # from our funding transaction using our own pubkey
        CTxIn(COutPoint(int(our_tx.hash, 16), 0), nSequence=0),
    )
    spc_tx = wallet.sign(spc, len(spc.vin) - 1, fee_bid)

    print(
        cyan(
            f"    - our transaction that will fund the spacechain one (plus OP_RETURN with spacechain block hash and change):"
        )
    )
    print(f"{white(our_tx.serialize().hex())}")

    print(
        cyan(
            f"    - the actual spacechain covenant transaction (index {next_pos}) with CTV hash equal to {magenta(get_tx(next_pos).ctv_hash().hex())}:"
        )
    )
    print(f"{white(spc_tx.serialize().hex())}")

    input(f"  (press Enter to publish)")

    our_txid = rpc.sendrawtransaction(our_tx.serialize().hex())
    print(yellow(f"> published {bold(white(our_txid))}."))

    spc_txid = rpc.sendrawtransaction(spc_tx.serialize().hex())
    print(yellow(f"> published {bold(white(spc_txid))}."))

    with s() as db:
        db["txs"][next_pos].id = spc_txid

    print()
    print(bold(green(f"CONGRATULATIONS! YOU'VE MINED A SPACECHAIN BLOCK!")))
    print(bold(green(f"=================================================")))
    print()
    time.sleep(2)

    return next_pos + 1


def find_spacechain_position_flow():
    print()
    print(yellow(f"> searching for the spacechain tip..."))
    for i in range(CHAIN_MAX + 1):
        txid = get_tx(i).id
        if txid:
            parent_txid = rpc.getrawtransaction(txid, 2)["vin"][-1]["txid"]
            spc_blockhash = bytes.fromhex(
                rpc.getrawtransaction(parent_txid, 2)["vout"][1]["scriptPubKey"]["asm"][
                    len("OP_RETURN ") :
                ]
            ).decode("utf-8")
            print(f"  - transaction {bold(i)} mined as {bold(green(txid))}")
            print(f"    with funding parent {bold(white(parent_txid))}")
            print(f"    and spacechain block hash {bold(blue(spc_blockhash))}")
            continue

        if i == 0:
            # this is the genesis, so we just assume we're starting a new spacechain
            print(
                yellow(
                    f"> this spacechain has not been bootstrapped yet (at least we don't know about it), so let's start it off"
                )
            )
            return 0

        # txid for this index not found, check if the previous is spent
        parent_is_unspent = rpc.gettxout(get_tx(i - 1).id, 0)
        if parent_is_unspent:
            print(f"  - transaction {bold(i)} not mined yet")
            return i

        # the parent is spent, which means this has been published
        # but we don't know under which txid, so we'll scan the utxo set
        redeem_script = CScript(
            [
                get_tx(i).ctv_hash(),
                script.OP_CHECKTEMPLATEVERIFY,
            ]
        )
        res = rpc.scantxoutset("start", [f"raw({redeem_script.hex()})"])
        for utxo in res["unspents"]:
            print(utxo)  # TODO

    return -1


def get_money_flow():
    global wallet
    private_key = bold(white(shorten(wallet.privkey.hex())))
    print(yellow(f"> loaded wallet with private key {private_key}"))

    while True:
        print(
            yellow(
                f"> scanning user wallet (fixed address) {magenta(bold(wallet.address))}..."
            )
        )
        wallet.scan()
        print(f"  UTXOs found: {len(wallet.coins)}")
        for utxo in wallet.coins:
            coin = italic(magenta("%064x:%i" % (utxo.outpoint.hash, utxo.outpoint.n)))
            print(f"  - {utxo.satoshis} satoshis at {coin}")

        if wallet.max_sendable > SATS_AMOUNT + 1000:
            break

        print(
            yellow(
                f"> fund your wallet by sending money to {white(bold(wallet.address))}"
            )
        )
        input("  (press Enter when you're done)")


def generate_transactions_flow():
    print(yellow(f"> pregenerating transactions for spacechain covenant string..."))
    txs = (get_tx(i) for i in range(CHAIN_MAX))
    for i, tx in enumerate(txs):
        ctv_hash = cyan(tx.ctv_hash().hex())
        amount = green(f"{tx.template.vout[0].nValue} sats")
        print(f"  - [{yellow(i)}] {amount}\n    ctv hash: {ctv_hash}")


def get_tx(i) -> SpacechainTx:
    id = None
    with s() as db:
        if i in db["txs"]:
            return db["txs"][i]

    # the last tx in the chain is always the same
    if i == CHAIN_MAX:
        last = CTransaction()
        last.nVersion = 2
        last.vin = [
            # CTV works with blank inputs, we will fill in later
            CTxIn(nSequence=0),
            CTxIn(nSequence=0),
        ]
        last.vout = [
            CTxOut(
                0,
                # the chain of transactions ends here with an OP_RETURN
                CScript([script.OP_RETURN, "simple-spacechain".encode("utf-8")]),
            )
        ]
        last.rehash()

        with s() as db:
            db["txs"][i] = SpacechainTx(tmpl_bytes=last.serialize())
    else:
        # recursion: we need the next one to calculate its CTV hash and commit here
        next = get_tx(i + 1)

        tx = CTransaction()
        tx.nVersion = 2
        tx.vin = [
            # CTV works with blank inputs, we will fill in later
            # one for the previous tx in the chain, the other for fee-bidding
            CTxIn(nSequence=0),
            CTxIn(nSequence=0),
        ]

        # the genesis tx will only have one input, the one we will use to fund it
        if i == 0:
            tx.vin = [CTxIn(nSequence=0)]

        tx.vout = [
            # this output continues the transaction chain
            CTxOut(
                SATS_AMOUNT,
                # bare CTV
                CScript(
                    [
                        next.ctv_hash(),  # CTV hash
                        script.OP_CHECKTEMPLATEVERIFY,
                    ]
                ),
            ),
        ]
        tx.rehash()

        with s() as db:
            db["txs"][i] = SpacechainTx(tmpl_bytes=tx.serialize())

    return get_tx(i)


if __name__ == "__main__":
    main()
