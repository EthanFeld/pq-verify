# Keccak round equivalence

`make formal-keccak-round` proves the round mapping with Yosys SAT:

- Generic versus LUT4-mapped round, RPC 1.
- Generic versus LUT4-mapped compositions, RPC 2.
- RPC 4 composition by induction from the universal one-round proof.
- Portable versus native Gowin `LUT4` cells for all four INIT functions, using
  Yosys's `gowin/cells_sim.v` model and all 16 possible input values.

The input state and starting round are symbolic. Full-state RPC1 and RPC2
miters constrain the starting round so every composed round stays within
Keccak's 24 rounds. The full-state RPC4 miter exceeded the practical runtime on
this host. The universal full-state RPC1 result proves both implementations
are the same function for every state and legal round index; applying that
equality after each round proves any valid composition, including RPC4. A
SymbiYosys cover target confirms the final legal starting round is reachable
for RPC1/2/4.

For the native-cell comparison, the RTL passes `NATIVE_LUT4=0` to the portable
truth-table model and `NATIVE_LUT4=1` to the Gowin primitive model. SAT checks
each primitive's truth table for every 4-bit input. Normal Gowin builds still
select the primitive by default when `PQ_GOWIN_LUT4` is defined.

If a full-state proof becomes too large on another solver or host, the round can
be decomposed at its five 64-bit column parities. Prove those parities equal,
then prove each theta/chi output lane using shared parity inputs; rho is fixed
bit wiring and iota uses the same round constant in both implementations.
