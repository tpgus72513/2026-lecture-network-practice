#!/usr/bin/env python3
"""Week 4 · Task 3 — Beat the fixed window.

Textbook §3.7.

`FixedWindow` is a sender that never adapts. It picks a window and keeps it,
forever, no matter what the network says back. It is not a strawman: it is what
you get if you skip congestion control entirely, and it was the internet's
actual failure mode in October 1986.

Write `YourControl` and beat it on the harness:

    python3 bench.py
    python3 bench.py --yours

The interface is two events and one number:

    .window        how many packets you are willing to have in flight
    .on_ack()      one packet made it there and back
    .on_loss()     a packet was dropped, or timed out waiting for its ACK

That is all the information a real TCP sender has. It cannot see the queue,
it cannot see the link rate, and neither can you. You infer them from these
two events, which is the entire idea of §3.7.
"""


class FixedWindow:
    """Send 64 packets at a time and never listen."""

    def __init__(self):
        self.window = 64

    def on_ack(self):
        pass

    def on_loss(self):
        pass


class YourControl:
    """Slow start, then "back off to the pipe and hold" (textbook §3.7).

    Loss is the only signal, and it only says one thing: the window just went
    over pipe + queue (about 20 + 10 = 30 here). Anywhere between 20 and 30
    nothing is lost, so a loss-only sender is blind there - it just fills the
    queue. So the goal is not to sit under the loss point, it is to sit at the
    pipe, about 2/3 of it, and to visit the loss point as rarely as possible.

      slow start  +1 per ACK until the first loss (the textbook's slow start)
      loss        if we were probing gently, we just crossed the cliff, so
                  cut to 2/3 of it, about the pipe. Any other loss means the
                  last cut was not enough, so halve (multiplicative decrease)
      hold        keep that window for HOLD ACKs: the link is full and the
                  queue is near empty, there is nothing to gain by growing
      probe       +1 per round trip (additive increase) until a loss says
                  where the cliff is now

    One cut per loss event. A loss is only reported after a 3-RTT timeout, so
    packets sent before a cut keep "failing" for 3 RTTs after it; at window W
    one RTT is about W ACKs, so losses are ignored for the next 3*W ACKs.
    """

    BETA_PROBE = 2 / 3     # cliff -> pipe:  20 / (20 + 10)
    BETA = 1 / 2           # the cut did not reach below the cliff
    HOLD = 1000            # ACKs to sit at the pipe before probing again

    def __init__(self):
        self.window = 1.0
        self.state = "slow start"
        self.held = 0          # ACKs since we started holding
        self.ignore = 0        # ACKs left during which losses are not new news

    def on_ack(self):
        if self.ignore:
            self.ignore -= 1
        if self.state == "slow start":
            self.window += 1
        elif self.state == "hold":
            self.held += 1
            if self.held >= self.HOLD:
                self.state = "probe"
        else:
            self.window += 1 / self.window

    def on_loss(self):
        if self.ignore:
            return                      # same congestion event as the last cut
        beta = self.BETA_PROBE if self.state == "probe" else self.BETA
        self.window = max(2.0, self.window * beta)
        self.state, self.held = "hold", 0
        self.ignore = int(3 * self.window)
