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

    pos = find_spacechain_position_flow()
    mine_next_block_flow(pos)


def mine_next_block_flow(
    next_pos,
    fee_bid=3000,
    spacechain_block_hash=b"spacechainblockhashgoeshere",
):
    # our transaction
    min_relay_fee = 500
    coin = wallet.biggest_coin
    our = CMutableTransaction()
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

    # spacechain transaction
    spc = CMutableTransaction.from_tx(get_tx(next_pos).template)
    spc.vin = []
    if next_pos > 0:
        # from the previous spacechain transaction
        curr_txid = get_tx(next_pos - 1).id
        spc.vin.append(
            CTxIn(COutPoint(txid_to_bytes(curr_txid), 0), nSequence=0),
        )
    spc.vin.append(
        # from our funding transaction using our own pubkey
        CTxIn(COutPoint(our_tx.GetTxid(), 0), nSequence=0),
    )
    spc_tx = wallet.sign(spc, len(spc.vin) - 1, fee_bid)

    print(
        cyan(
            f"    - our transaction that will fund the spacechain one (plus OP_RETURN with spacechain block hash and change):"
        )
    )
    print(f"{white(our_tx.serialize().hex())}")

    print(cyan(f"    - the actual spacechain covenant transaction:"))
    print(f"{white(spc_tx.serialize().hex())}")

    input(f"  (press Enter to publish)")

    our_txid = rpc.sendrawtransaction(our_tx.serialize().hex())
    print(yellow(f"> published {bold(white(our_txid))}."))

    spc_txid = rpc.sendrawtransaction(spc_tx.serialize().hex())
    print(yellow(f"> published {bold(white(spc_txid))}."))

    with s() as db:
        db["txs"][next_pos].id = spc_txid
        db["txs"][next_pos].spacechain_block_hash = spacechain_block_hash


def find_spacechain_position_flow():
    print()
    print(yellow(f"> searching for the spacechain tip..."))
    with s() as db:
        for i in range(CHAIN_MAX):
            txid = db["txs"][i].id
            if txid:
                print(f"  - transaction {i} mined as {bold(white(txid))}")
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
            parent_is_unspent = rpc.gettxout(db["txs"][i - 1].id, 0)
            if parent_is_unspent:
                print(f"  - transaction {i} not mined yet")
                return i

            # the parent is spent, which means this has been published
            # but we don't know under which txid, so we'll scan the utxo set
            redeem_script = CScript(
                [
                    get_standard_template_hash(db["txs"][i].template, 0),
                    OP_CHECKTEMPLATEVERIFY,
                ]
            )
            res = rpc.scantxoutset("start", [f"raw({redeem_script.hex()})"])
            for utxo in res["unspents"]:
                print(utxo)  # TODO

    return CHAIN_MAX


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
    print(yellow(f"> pregenerating transactions for spacechain covenant string..."))
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
            db["txs"][i] = SpacechainTx(tmpl_bytes=marshal_tx(last))
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

        # the genesis tx will only have one input, the one we will use to fund it
        if i == 0:
            tx.vin = [CTxIn()]

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

        print(tx.serialize().hex())

        with s() as db:
            db["txs"][i] = SpacechainTx(tmpl_bytes=marshal_tx(tx))

    return get_tx(i)


if __name__ == "__main__":
    main()
