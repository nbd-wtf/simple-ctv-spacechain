Simple CTV Spacechain
=====================

[![asciicast](https://asciinema.org/a/iRC5fXcuNmuvkbMoGMbeOuVA0.svg)](https://asciinema.org/a/iRC5fXcuNmuvkbMoGMbeOuVA0)

This is a demo of a CTV-based [Spacechain](https://www.youtube.com/watch?v=N2ow4Q34Jeg).

To run it you need
  - CTV Signet: https://github.com/jeremyrubin/bitcoin/tree/checktemplateverify-signet-23.0-alpha
  - `git clone git@github.com:fiatjaf/simple-ctv-spacechain`
  - Install dependencies (in my case with `virtualenv venv && ./venv/bin/pip install -r requirements.txt`) and run `main.py`

Run `main.py` (in my case `./venv/bin/python main.py`) and you'll be prompted send coins to an address. You can get coins at https://faucet.ctvsignet.com/.

Then the demo will progressively generate transactions that spend from each other with CTV + an input from your wallet in which you also specify a block hash for the hypothetical spacechain.

(We don't have the _actual_ spacechain part here, just the blind merged mining part.)

You can stop the program flow and continue later if you want.

Please stop at each step to inspect the transactions that were generated and see how they fit beautifully with each other.

---

If you have questions or you just love spacechains, please go to https://t.me/spacechains!
