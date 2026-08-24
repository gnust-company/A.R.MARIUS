"""Infrastructure for the on-machine daemon runtime (feature 002).

Everything that knows about machines, workplaces and run claims lives here, behind the
adapter contract. The domain and application layers never import from this package —
`test_constitution_guards.py` enforces that.
"""
