"""Corporate actions: detection and adjustment (M39).

M60 built the containment - reconciliation can be told a difference is explained,
and a position can be put in a state the ordinary path refuses to treat as
ordinary. This is the other half.

Built as its own subsystem rather than as more methods on `SignalToOrderBridge`,
for two reasons that are requirements rather than taste: the state must be
readable from every screen it bears on, and it must be available to the
autonomous decision path. Both want a queryable domain concept.
"""
