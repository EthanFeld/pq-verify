# Command-controller protocol proof

`make formal-cmd-ctrl` runs a bounded check of `cmd_ctrl` from its raw byte
interface. The proof reaches VERIFY start only after parsing the frame command,
length, mode, and context-length prefix with loaded public key and signature.
It checks bad-CRC rejection, a busy VERIFY reply, and response preservation when
the verifier completes on the same cycle as another frame's CRC.

The wrapper uses 1-byte public-key and 4-byte signature parameters to keep the
proof short. Production defaults remain 32 and 7,856 bytes. UART RX/TX timing is
bypassed; ready handshakes are held high. The environment allows a new request
only when response and deferred-response channels are empty, while the verifier
completion is constrained to be a one-cycle pulse after a start.

The BMC bound is 144 formal steps (72 command-controller clocks). Six covers
reach a valid VERIFY start, busy response, immediate bad-CRC response, and active
bad-CRC response. Additional covers exercise simultaneous completion and
subsequent delivery of a deferred busy VERIFY reply. This is bounded control
verification, not proof of UART bit timing or cryptographic data correctness.
