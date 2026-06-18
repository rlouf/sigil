"""Core content-addressed substrate for Zeta.

The substrate separates three concerns that are easy to blur in agent
systems:

* `Object` stores immutable values by content.
* `RefName` gives mutable names to the latest object for a logical source.
* `Derivation` records how one object was built from other objects.

This split gives Zeta build-system-like behavior without making prompt
assembly or model calls special. A context sent to a model is just an object.
A model output can be stored as an object. A generated file can be stored as
an object. Refs connect those immutable values to moving names such as
`session/s1/head` or `file/REFERENCES.md`.

Object identity is based on canonical JSON. The store hashes an envelope
containing `kind`, `schema`, `data`, and structural `links`; operational facts
such as timestamps, retries, latency, or worker identity do not belong in an
object. If those facts matter, record them outside the value plane.
"""

from zeta.substrate.derivation import Derivation
from zeta.substrate.object import Object, ObjectId
from zeta.substrate.ref import Ref, RefName, RefUpdate

__all__ = [
    "Derivation",
    "Object",
    "ObjectId",
    "Ref",
    "RefName",
    "RefUpdate",
]
