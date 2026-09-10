"""Musical knowledge that RDX owns in code rather than in model weights.

Everything here is deterministic and tested, so a producer can read what
"warm" or "buildup" actually does and correct it. The language model chooses
which of these to apply and how strongly; it never invents the mechanism.
"""
